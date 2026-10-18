import uuid
from pathlib import Path
from typing import Callable

from construction_intelligence.documents import read_pdf_document
from construction_intelligence.gemini_analysis import analyze_meeting
from construction_intelligence.matching import (
    choose_issue_prefix,
    find_candidate_issues,
    generate_issue_id,
)
from construction_intelligence.models import ExtractedIssue, MeetingAnalysis
from construction_intelligence.state_store import current_timestamp, save_state
from construction_intelligence.validation import validate_meeting_analysis


ProgressCallback = Callable[[str, int, int], None]


def register_document(state: dict, file_path: str | Path) -> tuple[str, bool]:
    """Import a PDF document and prevent duplicate processing."""
    document_record = read_pdf_document(file_path)
    for existing_document_id, existing_document in state["documents"].items():
        if existing_document["fingerprint"] == document_record["fingerprint"]:
            return existing_document_id, False
    document_record["imported_at"] = current_timestamp()
    document_record["analysis_status"] = "pending"
    state["documents"][document_record["document_id"]] = document_record
    return document_record["document_id"], True


def create_issue_record(
    issue_id: str,
    extracted_issue: ExtractedIssue,
    document_id: str,
    meeting_record: dict,
) -> dict:
    """Create a persistent issue from a new extracted finding."""
    extracted_data = extracted_issue.model_dump(mode="json")
    issue_event = create_issue_event(
        extracted_issue,
        document_id,
        meeting_record,
        "created",
    )
    return {
        "issue_id": issue_id,
        "title": extracted_issue.title,
        "discipline": extracted_issue.discipline,
        "category": extracted_issue.category,
        "status": extracted_issue.status,
        "significance": extracted_issue.significance,
        "first_reported": meeting_record["meeting_id"],
        "last_discussed": meeting_record["meeting_id"],
        "meeting_ids": [meeting_record["meeting_id"]],
        "created_at": current_timestamp(),
        "updated_at": current_timestamp(),
        "current_assessment": extracted_data,
        "events": [issue_event],
        "review_status": "accepted",
    }


def create_issue_event(
    extracted_issue: ExtractedIssue,
    document_id: str,
    meeting_record: dict,
    event_type: str,
) -> dict:
    """Create an auditable issue-history event."""
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "document_id": document_id,
        "meeting_id": meeting_record["meeting_id"],
        "meeting_date": meeting_record.get("meeting_date"),
        "recorded_at": current_timestamp(),
        "assessment": extracted_issue.model_dump(mode="json"),
    }


def update_issue_record(
    stored_issue: dict,
    extracted_issue: ExtractedIssue,
    document_id: str,
    meeting_record: dict,
) -> None:
    """Append evidence and update the current issue assessment."""
    stored_issue["events"].append(
        create_issue_event(
            extracted_issue,
            document_id,
            meeting_record,
            "updated",
        )
    )
    if meeting_record["meeting_id"] not in stored_issue["meeting_ids"]:
        stored_issue["meeting_ids"].append(meeting_record["meeting_id"])
    stored_issue["title"] = extracted_issue.title
    stored_issue["discipline"] = extracted_issue.discipline
    stored_issue["category"] = extracted_issue.category
    stored_issue["status"] = extracted_issue.status
    stored_issue["significance"] = extracted_issue.significance
    stored_issue["last_discussed"] = meeting_record["meeting_id"]
    stored_issue["updated_at"] = current_timestamp()
    stored_issue["current_assessment"] = extracted_issue.model_dump(mode="json")


def add_match_review_item(
    state: dict,
    extracted_issue: ExtractedIssue,
    candidates: list[dict],
    document_id: str,
    meeting_record: dict,
) -> None:
    """Hold an uncertain historical match for human review."""
    state["review_queue"].append(
        {
            "review_id": str(uuid.uuid4()),
            "review_type": "possible_issue_match",
            "status": "pending",
            "created_at": current_timestamp(),
            "document_id": document_id,
            "meeting_id": meeting_record["meeting_id"],
            "finding": extracted_issue.model_dump(mode="json"),
            "candidates": candidates,
        }
    )


def apply_extracted_issue(
    state: dict,
    extracted_issue: ExtractedIssue,
    document_id: str,
    meeting_record: dict,
) -> str | None:
    """Match, hold or create an issue without unsafe automatic merges."""
    stored_issues = state["issues"]
    model_candidate_id = extracted_issue.possible_existing_issue_id
    if (
        model_candidate_id in stored_issues
        and extracted_issue.match_confidence >= 0.82
    ):
        update_issue_record(
            stored_issues[model_candidate_id],
            extracted_issue,
            document_id,
            meeting_record,
        )
        return model_candidate_id

    deterministic_candidates = find_candidate_issues(extracted_issue, stored_issues)
    if deterministic_candidates:
        strongest_candidate = deterministic_candidates[0]
        if strongest_candidate["similarity"] >= 0.78:
            target_issue_id = strongest_candidate["issue_id"]
            update_issue_record(
                stored_issues[target_issue_id],
                extracted_issue,
                document_id,
                meeting_record,
            )
            return target_issue_id
        if strongest_candidate["similarity"] >= 0.48:
            add_match_review_item(
                state,
                extracted_issue,
                deterministic_candidates,
                document_id,
                meeting_record,
            )
            return None

    issue_prefix = choose_issue_prefix(
        extracted_issue.category,
        extracted_issue.discipline,
    )
    new_issue_id = generate_issue_id(stored_issues, issue_prefix)
    stored_issues[new_issue_id] = create_issue_record(
        new_issue_id,
        extracted_issue,
        document_id,
        meeting_record,
    )
    return new_issue_id


def apply_meeting_analysis(
    state: dict,
    document_id: str,
    meeting_record: dict,
    meeting_analysis: MeetingAnalysis,
) -> list[str]:
    """Commit a validated meeting analysis to persistent issue history."""
    affected_issue_ids = []
    for extracted_issue in meeting_analysis.issues:
        affected_issue_id = apply_extracted_issue(
            state,
            extracted_issue,
            document_id,
            meeting_record,
        )
        if affected_issue_id:
            affected_issue_ids.append(affected_issue_id)
    meeting_record["analysis"] = meeting_analysis.model_dump(mode="json")
    meeting_record["analysis_status"] = "complete"
    meeting_record["affected_issue_ids"] = affected_issue_ids
    meeting_record["analysed_at"] = current_timestamp()
    return affected_issue_ids


def add_validation_review_item(
    state: dict,
    document_id: str,
    meeting_record: dict,
    meeting_analysis: MeetingAnalysis,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Hold an invalid AI result for human review."""
    state["review_queue"].append(
        {
            "review_id": str(uuid.uuid4()),
            "review_type": "validation_failure",
            "status": "pending",
            "created_at": current_timestamp(),
            "document_id": document_id,
            "meeting_id": meeting_record["meeting_id"],
            "errors": errors,
            "warnings": warnings,
            "analysis": meeting_analysis.model_dump(mode="json"),
        }
    )
    meeting_record["analysis_status"] = "review_required"


def find_review_item(state: dict, review_id: str) -> dict:
    """Find one review item by identifier."""
    review_item = next(
        (
            queued_review
            for queued_review in state["review_queue"]
            if queued_review["review_id"] == review_id
        ),
        None,
    )
    if review_item is None:
        raise KeyError(f"Unknown review item: {review_id}")
    return review_item


def find_meeting_record(state: dict, document_id: str, meeting_id: str) -> dict:
    """Find one imported meeting record."""
    document_record = state["documents"].get(document_id)
    if document_record is None:
        raise KeyError(f"Unknown document: {document_id}")
    meeting_record = next(
        (
            imported_meeting
            for imported_meeting in document_record["meetings"]
            if imported_meeting["meeting_id"] == meeting_id
        ),
        None,
    )
    if meeting_record is None:
        raise KeyError(f"Unknown meeting: {meeting_id}")
    return meeting_record


def resolve_match_review(
    state: dict,
    review_id: str,
    resolution: str,
    target_issue_id: str | None = None,
) -> str | None:
    """Resolve an uncertain issue match through an explicit user decision."""
    review_item = find_review_item(state, review_id)
    if review_item.get("status") != "pending":
        raise ValueError("This review item has already been resolved.")
    if resolution == "dismissed":
        review_item["status"] = "dismissed"
        review_item["resolved_at"] = current_timestamp()
        review_item["resolution"] = "dismissed"
        return None
    if review_item.get("review_type") != "possible_issue_match":
        raise ValueError("Only possible issue matches can be created or merged.")
    extracted_issue = ExtractedIssue.model_validate(review_item["finding"])
    meeting_record = find_meeting_record(
        state,
        review_item["document_id"],
        review_item["meeting_id"],
    )
    if resolution == "new_issue":
        issue_prefix = choose_issue_prefix(
            extracted_issue.category,
            extracted_issue.discipline,
        )
        resolved_issue_id = generate_issue_id(state["issues"], issue_prefix)
        state["issues"][resolved_issue_id] = create_issue_record(
            resolved_issue_id,
            extracted_issue,
            review_item["document_id"],
            meeting_record,
        )
    elif resolution == "merged":
        if target_issue_id not in state["issues"]:
            raise KeyError(f"Unknown target issue: {target_issue_id}")
        resolved_issue_id = target_issue_id
        update_issue_record(
            state["issues"][resolved_issue_id],
            extracted_issue,
            review_item["document_id"],
            meeting_record,
        )
    else:
        raise ValueError(f"Unsupported review resolution: {resolution}")
    review_item["status"] = "resolved"
    review_item["resolved_at"] = current_timestamp()
    review_item["resolution"] = resolution
    review_item["resolved_issue_id"] = resolved_issue_id
    return resolved_issue_id


def analyze_document(
    state: dict,
    document_id: str,
    state_path: str | Path,
    api_key: str | None,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    """Analyse pending meetings incrementally and save after each result."""
    if document_id not in state["documents"]:
        raise KeyError(f"Unknown document: {document_id}")
    document_record = state["documents"][document_id]
    pending_meetings = [
        meeting_record
        for meeting_record in document_record["meetings"]
        if meeting_record.get("analysis_status") != "complete"
    ]
    maximum_meetings = int(state["settings"].get("maximum_meetings_per_run", 20))
    meetings_to_process = pending_meetings[:maximum_meetings]
    run_record = {
        "run_id": str(uuid.uuid4()),
        "document_id": document_id,
        "started_at": current_timestamp(),
        "completed_at": None,
        "status": "running",
        "model": state["settings"]["model"],
        "processed_meetings": [],
        "errors": [],
        "usage": [],
    }
    state["runs"].append(run_record)
    document_record["analysis_status"] = "processing"
    save_state(state, state_path)

    for meeting_index, meeting_record in enumerate(meetings_to_process, start=1):
        if progress_callback:
            progress_callback(
                f"Analysing {meeting_record['meeting_id']}",
                meeting_index - 1,
                len(meetings_to_process),
            )
        try:
            meeting_analysis, usage_metadata = analyze_meeting(
                meeting_record=meeting_record,
                stored_issues=state["issues"],
                api_key=api_key,
                model_name=state["settings"]["model"],
                enabled_specialists=state["settings"]["enabled_specialists"],
                analysis_depth=state["settings"]["analysis_depth"],
            )
            validation_result = validate_meeting_analysis(
                meeting_analysis,
                meeting_record["source_pages"],
            )
            if validation_result.valid:
                apply_meeting_analysis(
                    state,
                    document_id,
                    meeting_record,
                    meeting_analysis,
                )
            else:
                add_validation_review_item(
                    state,
                    document_id,
                    meeting_record,
                    meeting_analysis,
                    validation_result.errors,
                    validation_result.warnings,
                )
            run_record["processed_meetings"].append(meeting_record["meeting_id"])
            run_record["usage"].append(usage_metadata)
            save_state(state, state_path)
        except Exception as analysis_error:
            meeting_record["analysis_status"] = "failed"
            meeting_record["analysis_error"] = str(analysis_error)
            run_record["errors"].append(
                {
                    "meeting_id": meeting_record["meeting_id"],
                    "error": str(analysis_error),
                }
            )
            save_state(state, state_path)

    remaining_meetings = [
        meeting_record
        for meeting_record in document_record["meetings"]
        if meeting_record.get("analysis_status") != "complete"
    ]
    document_record["analysis_status"] = "complete" if not remaining_meetings else "attention_required"
    run_record["completed_at"] = current_timestamp()
    run_record["status"] = "complete" if not run_record["errors"] else "completed_with_errors"
    save_state(state, state_path)
    if progress_callback:
        progress_callback(
            "Analysis complete",
            len(meetings_to_process),
            len(meetings_to_process),
        )
    return run_record

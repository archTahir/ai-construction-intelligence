from construction_intelligence.models import MeetingAnalysis, ValidationResult


def validate_source_evidence(
    meeting_analysis: MeetingAnalysis,
    available_source_pages: set[int],
) -> tuple[list[str], list[str]]:
    """Validate evidence passages and source-page references."""
    validation_errors = []
    validation_warnings = []
    for issue_index, extracted_issue in enumerate(meeting_analysis.issues, start=1):
        if not extracted_issue.source_evidence:
            validation_errors.append(f"Issue {issue_index} has no source evidence.")
        for evidence_index, source_evidence in enumerate(
            extracted_issue.source_evidence,
            start=1,
        ):
            if not source_evidence.passage.strip():
                validation_errors.append(
                    f"Issue {issue_index} evidence {evidence_index} has no passage."
                )
            if (
                source_evidence.source_page is not None
                and available_source_pages
                and source_evidence.source_page not in available_source_pages
            ):
                validation_errors.append(
                    f"Issue {issue_index} evidence {evidence_index} refers to an unavailable source page."
                )
            if source_evidence.evidence_type == "ai_inference":
                validation_warnings.append(
                    f"Issue {issue_index} includes an AI inference that requires human review."
                )
    return validation_errors, validation_warnings


def validate_status_transitions(meeting_analysis: MeetingAnalysis) -> list[str]:
    """Validate high-impact status claims against their evidence."""
    validation_errors = []
    for issue_index, extracted_issue in enumerate(meeting_analysis.issues, start=1):
        if extracted_issue.status == "closed_verified":
            verified_evidence = [
                source_evidence
                for source_evidence in extracted_issue.source_evidence
                if source_evidence.evidence_type == "verified_conclusion"
            ]
            if not verified_evidence:
                validation_errors.append(
                    f"Issue {issue_index} is marked closed without verified closure evidence."
                )
        if extracted_issue.match_confidence > 0 and not extracted_issue.possible_existing_issue_id:
            validation_errors.append(
                f"Issue {issue_index} has match confidence without a candidate issue identifier."
            )
    return validation_errors


def validate_meeting_analysis(
    meeting_analysis: MeetingAnalysis,
    source_pages: list[int | None],
) -> ValidationResult:
    """Run deterministic checks before committing AI findings."""
    available_source_pages = {
        source_page for source_page in source_pages if source_page is not None
    }
    evidence_errors, evidence_warnings = validate_source_evidence(
        meeting_analysis,
        available_source_pages,
    )
    status_errors = validate_status_transitions(meeting_analysis)
    meeting_errors = []
    if not meeting_analysis.meeting_id.strip():
        meeting_errors.append("Meeting analysis has no meeting identifier.")
    validation_errors = meeting_errors + evidence_errors + status_errors
    return ValidationResult(
        valid=not validation_errors,
        errors=validation_errors,
        warnings=evidence_warnings,
    )


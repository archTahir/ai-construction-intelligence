import csv
import json
from pathlib import Path


def export_state_json(state: dict, output_path: str | Path) -> Path:
    """Export the complete state as readable JSON."""
    resolved_output_path = Path(output_path)
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_output_path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return resolved_output_path


def export_issue_register_csv(state: dict, output_path: str | Path) -> Path:
    """Export the current issue register as CSV."""
    resolved_output_path = Path(output_path)
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    field_names = [
        "issue_id",
        "title",
        "discipline",
        "category",
        "status",
        "significance",
        "first_reported",
        "last_discussed",
        "summary",
        "approval_status",
        "evidence_status",
        "recommended_verification",
    ]
    with resolved_output_path.open("w", encoding="utf-8", newline="") as output_file:
        csv_writer = csv.DictWriter(output_file, fieldnames=field_names)
        csv_writer.writeheader()
        for issue_id, issue_record in sorted(state["issues"].items()):
            current_assessment = issue_record.get("current_assessment", {})
            csv_writer.writerow(
                {
                    "issue_id": issue_id,
                    "title": issue_record.get("title"),
                    "discipline": issue_record.get("discipline"),
                    "category": issue_record.get("category"),
                    "status": issue_record.get("status"),
                    "significance": issue_record.get("significance"),
                    "first_reported": issue_record.get("first_reported"),
                    "last_discussed": issue_record.get("last_discussed"),
                    "summary": current_assessment.get("summary"),
                    "approval_status": current_assessment.get("approval_status"),
                    "evidence_status": current_assessment.get("evidence_status"),
                    "recommended_verification": current_assessment.get("recommended_verification"),
                }
            )
    return resolved_output_path


import unittest

from construction_intelligence.models import ExtractedIssue, SourceEvidence
from construction_intelligence.pipeline import apply_extracted_issue, resolve_match_review
from construction_intelligence.state_store import create_default_state


def create_issue(title: str) -> ExtractedIssue:
    """Create an extracted pipeline issue."""
    return ExtractedIssue(
        title=title,
        discipline="Mechanical",
        category="Programme and Procurement",
        system="HVAC",
        component="Z275 ductwork",
        location="Hospital building",
        summary="Specified ductwork remains delayed in procurement.",
        status="blocked",
        significance="high",
        evidence_status="documented",
        programme_implications=["Installation start may be delayed."],
        recommended_verification="Review procurement evidence and programme impact.",
        source_evidence=[
            SourceEvidence(
                source_page=3,
                passage="The specified material is not locally available.",
                evidence_type="party_reported_claim",
            )
        ],
    )


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        """Create an empty state and meeting record."""
        self.state = create_default_state()
        self.meeting_record = {
            "meeting_id": "M05",
            "meeting_date": "06/05/2023",
        }

    def test_new_issue_is_created(self) -> None:
        """Create a persistent issue when no candidate exists."""
        issue_id = apply_extracted_issue(
            self.state,
            create_issue("Z275 ductwork procurement"),
            "DOC-001",
            self.meeting_record,
        )
        self.assertEqual(issue_id, "PROG-001")
        self.assertIn(issue_id, self.state["issues"])

    def test_high_confidence_catalog_match_updates_history(self) -> None:
        """Append an event to a strong model-identified historical match."""
        first_issue = create_issue("Z275 ductwork procurement")
        first_issue_id = apply_extracted_issue(
            self.state,
            first_issue,
            "DOC-001",
            self.meeting_record,
        )
        second_meeting = {"meeting_id": "M06", "meeting_date": "13/05/2023"}
        second_issue = create_issue("Z275 ductwork procurement update")
        second_issue.possible_existing_issue_id = first_issue_id
        second_issue.match_confidence = 0.95
        updated_issue_id = apply_extracted_issue(
            self.state,
            second_issue,
            "DOC-001",
            second_meeting,
        )
        self.assertEqual(updated_issue_id, first_issue_id)
        self.assertEqual(len(self.state["issues"][first_issue_id]["events"]), 2)

    def test_user_can_create_new_issue_from_match_review(self) -> None:
        """Resolve an uncertain match as a separate issue."""
        document_id = "DOC-001"
        self.state["documents"][document_id] = {
            "meetings": [self.meeting_record],
        }
        first_issue = create_issue("Z275 ductwork procurement")
        first_issue_id = apply_extracted_issue(
            self.state,
            first_issue,
            document_id,
            self.meeting_record,
        )
        uncertain_issue = create_issue("Smoke extraction ductwork alternative")
        review_id = "REVIEW-001"
        self.state["review_queue"].append(
            {
                "review_id": review_id,
                "review_type": "possible_issue_match",
                "status": "pending",
                "document_id": document_id,
                "meeting_id": self.meeting_record["meeting_id"],
                "finding": uncertain_issue.model_dump(mode="json"),
                "candidates": [{"issue_id": first_issue_id}],
            }
        )
        resolved_issue_id = resolve_match_review(
            self.state,
            review_id,
            "new_issue",
        )
        self.assertEqual(resolved_issue_id, "PROG-002")
        self.assertEqual(self.state["review_queue"][0]["status"], "resolved")


if __name__ == "__main__":
    unittest.main()

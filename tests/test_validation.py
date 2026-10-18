import unittest

from construction_intelligence.models import ExtractedIssue, MeetingAnalysis, SourceEvidence
from construction_intelligence.validation import validate_meeting_analysis


def create_meeting_analysis(status: str, evidence_type: str) -> MeetingAnalysis:
    """Create a meeting analysis for validator tests."""
    return MeetingAnalysis(
        meeting_id="M01",
        meeting_date="01/04/2023",
        summary="A technical issue was reviewed.",
        issues=[
            ExtractedIssue(
                title="Facade waterproofing",
                discipline="Architectural",
                category="Technical Compliance",
                system="Building envelope",
                summary="Approval remains unresolved.",
                status=status,
                significance="high",
                evidence_status="incomplete",
                recommended_verification="Obtain formal approval.",
                source_evidence=[
                    SourceEvidence(
                        source_page=2,
                        passage="Formal approval remains outstanding.",
                        evidence_type=evidence_type,
                    )
                ],
            )
        ],
    )


class ValidationTests(unittest.TestCase):
    def test_supported_open_issue_is_valid(self) -> None:
        """Accept evidence-supported unresolved findings."""
        meeting_analysis = create_meeting_analysis(
            "under_review",
            "documented_statement",
        )
        validation_result = validate_meeting_analysis(meeting_analysis, [1, 2])
        self.assertTrue(validation_result.valid)

    def test_unverified_closure_is_rejected(self) -> None:
        """Reject closure without verified evidence."""
        meeting_analysis = create_meeting_analysis(
            "closed_verified",
            "party_reported_claim",
        )
        validation_result = validate_meeting_analysis(meeting_analysis, [1, 2])
        self.assertFalse(validation_result.valid)
        self.assertIn("verified closure evidence", validation_result.errors[0])

    def test_unknown_source_page_is_rejected(self) -> None:
        """Reject evidence referencing a page absent from the meeting."""
        meeting_analysis = create_meeting_analysis(
            "under_review",
            "documented_statement",
        )
        validation_result = validate_meeting_analysis(meeting_analysis, [1])
        self.assertFalse(validation_result.valid)


if __name__ == "__main__":
    unittest.main()


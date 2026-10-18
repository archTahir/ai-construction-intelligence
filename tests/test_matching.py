import unittest

from construction_intelligence.matching import (
    calculate_issue_similarity,
    generate_issue_id,
)
from construction_intelligence.models import ExtractedIssue, SourceEvidence


def create_issue(title: str, system: str, location: str) -> ExtractedIssue:
    """Create a valid extracted issue for matching tests."""
    return ExtractedIssue(
        title=title,
        discipline="Architectural",
        category="Technical Compliance",
        system=system,
        component="Waterproofing membrane",
        location=location,
        summary="Required performance evidence remains incomplete.",
        status="under_review",
        significance="high",
        evidence_status="incomplete",
        recommended_verification="Obtain the complete technical submission.",
        source_evidence=[
            SourceEvidence(
                source_page=2,
                passage="The required documents remain outstanding.",
                evidence_type="documented_statement",
            )
        ],
    )


class MatchingTests(unittest.TestCase):
    def test_same_case_scores_higher_than_different_location(self) -> None:
        """Use structured context rather than keywords alone."""
        extracted_issue = create_issue(
            "Facade waterproofing compliance",
            "Building envelope",
            "External elevations",
        )
        same_case = {
            "title": "Facade waterproofing approval",
            "discipline": "Architectural",
            "category": "Technical Compliance",
            "current_assessment": {
                "system": "Building envelope",
                "component": "Waterproofing membrane",
                "location": "External elevations",
                "summary": "Performance evidence is incomplete.",
            },
        }
        different_case = {
            "title": "Wet area waterproofing",
            "discipline": "Architectural",
            "category": "Technical Compliance",
            "current_assessment": {
                "system": "Internal wet areas",
                "component": "Waterproofing membrane",
                "location": "Bathrooms",
                "summary": "Performance evidence is incomplete.",
            },
        }
        same_score = calculate_issue_similarity(extracted_issue, same_case)
        different_score = calculate_issue_similarity(extracted_issue, different_case)
        self.assertGreater(same_score, different_score)

    def test_issue_identifier_increments(self) -> None:
        """Generate a stable next identifier."""
        stored_issues = {"TECH-001": {}, "TECH-004": {}, "COM-001": {}}
        self.assertEqual(generate_issue_id(stored_issues, "TECH"), "TECH-005")


if __name__ == "__main__":
    unittest.main()


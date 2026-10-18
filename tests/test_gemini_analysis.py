import unittest
from unittest.mock import MagicMock, patch

from construction_intelligence.gemini_analysis import analyze_meeting, select_specialists
from construction_intelligence.models import MeetingAnalysis


class GeminiAnalysisTests(unittest.TestCase):
    def test_specialist_routing_uses_meeting_subjects(self) -> None:
        """Select only specialist perspectives relevant to meeting text."""
        selected_specialists = select_specialists(
            "The BOQ deviation affects payment and procurement delivery.",
            [
                "engineering",
                "contract_commercial",
                "programme_procurement",
                "quality_compliance",
            ],
        )
        self.assertIn("contract_commercial", selected_specialists)
        self.assertIn("programme_procurement", selected_specialists)
        self.assertNotIn("engineering", selected_specialists)

    @patch("construction_intelligence.gemini_analysis.genai.Client")
    def test_structured_analysis_uses_parsed_response(self, client_factory: MagicMock) -> None:
        """Return the SDK structured response as a validated model."""
        parsed_analysis = MeetingAnalysis(
            meeting_id="M01",
            meeting_date="01/04/2023",
            summary="No significant issue was identified.",
        )
        generation_response = MagicMock()
        generation_response.parsed = parsed_analysis
        generation_response.usage_metadata = None
        client_instance = client_factory.return_value
        client_instance.models.generate_content.return_value = generation_response
        meeting_record = {
            "meeting_id": "M01",
            "meeting_date": "01/04/2023",
            "text": "===== SOURCE PAGE 1 =====\nRoutine administrative update.",
        }
        meeting_analysis, usage_metadata = analyze_meeting(
            meeting_record=meeting_record,
            stored_issues={},
            api_key="test-key",
            model_name="gemini-flash-latest",
            enabled_specialists=["engineering"],
            analysis_depth="standard",
        )
        self.assertEqual(meeting_analysis.meeting_id, "M01")
        self.assertEqual(usage_metadata, {})
        client_instance.models.generate_content.assert_called_once()
        client_instance.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()


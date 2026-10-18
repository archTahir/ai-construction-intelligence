import json
import os

from google import genai
from google.genai import types

from construction_intelligence.models import MeetingAnalysis
from construction_intelligence.rulebook import build_system_instruction


SPECIALIST_KEYWORDS = {
    "engineering": {
        "engineering",
        "technical",
        "design",
        "drawing",
        "structure",
        "hvac",
        "electrical",
        "mechanical",
        "facade",
        "waterproofing",
    },
    "contract_commercial": {
        "contract",
        "commercial",
        "boq",
        "variation",
        "payment",
        "ipa",
        "claim",
        "eot",
    },
    "programme_procurement": {
        "programme",
        "schedule",
        "delay",
        "procurement",
        "delivery",
        "milestone",
        "sequence",
    },
    "quality_compliance": {
        "quality",
        "compliance",
        "ncr",
        "inspection",
        "defect",
        "approval",
        "certificate",
        "rectification",
    },
}


def resolve_api_key(api_key: str | None = None) -> str:
    """Resolve the Gemini API key without persisting it."""
    resolved_api_key = api_key or os.getenv("GEMINI_API_KEY", "")
    if not resolved_api_key.strip():
        raise ValueError("A Gemini API key is required.")
    return resolved_api_key.strip()


def select_specialists(meeting_text: str, enabled_specialists: list[str]) -> list[str]:
    """Select relevant specialist instruction sets for a meeting."""
    normalized_meeting_text = meeting_text.lower()
    selected_specialists = []
    for specialist_name in enabled_specialists:
        specialist_keywords = SPECIALIST_KEYWORDS.get(specialist_name, set())
        if not specialist_keywords or any(
            keyword in normalized_meeting_text for keyword in specialist_keywords
        ):
            selected_specialists.append(specialist_name)
    return selected_specialists or ["document_intelligence"]


def build_issue_catalog(stored_issues: dict[str, dict]) -> list[dict]:
    """Build a concise issue catalog for historical matching."""
    issue_catalog = []
    for issue_id, stored_issue in stored_issues.items():
        current_assessment = stored_issue.get("current_assessment", {})
        issue_catalog.append(
            {
                "issue_id": issue_id,
                "title": stored_issue.get("title"),
                "discipline": stored_issue.get("discipline"),
                "category": stored_issue.get("category"),
                "system": current_assessment.get("system"),
                "component": current_assessment.get("component"),
                "location": current_assessment.get("location"),
                "status": stored_issue.get("status"),
                "last_summary": current_assessment.get("summary"),
            }
        )
    return issue_catalog[-80:]


def build_analysis_prompt(meeting_record: dict, issue_catalog: list[dict]) -> str:
    """Build the meeting extraction prompt."""
    issue_catalog_text = json.dumps(issue_catalog, ensure_ascii=False, indent=2)
    return f"""Analyse this construction meeting record in detail.

Meeting identifier: {meeting_record['meeting_id']}
Meeting date: {meeting_record.get('meeting_date') or 'unknown'}

Existing issue catalog:
{issue_catalog_text}

For each significant issue, preserve the exact topic, discipline, system, component, location, current status, approval stage, missing evidence, responsibilities, actions, deadlines, technical implications, commercial implications, programme implications, quality implications and next verification step.

When an event appears to continue an existing issue, set possible_existing_issue_id to its exact catalog identifier and provide a confidence value. Use zero confidence and a null identifier for new issues. Do not merge unrelated issues based only on shared words.

Use the SOURCE PAGE markers in the text for evidence references. Do not use the consolidated PDF page number as the source page. Treat repeated English and French passages as a single event.

Meeting record:
{meeting_record['text']}"""


def read_usage_metadata(generation_response: object) -> dict:
    """Read token usage from a Gemini response."""
    usage_metadata = getattr(generation_response, "usage_metadata", None)
    if usage_metadata is None:
        return {}
    if hasattr(usage_metadata, "model_dump"):
        return usage_metadata.model_dump(mode="json", exclude_none=True)
    return {}


def analyze_meeting(
    meeting_record: dict,
    stored_issues: dict[str, dict],
    api_key: str | None,
    model_name: str,
    enabled_specialists: list[str],
    analysis_depth: str,
) -> tuple[MeetingAnalysis, dict]:
    """Extract validated structured intelligence from one meeting."""
    resolved_api_key = resolve_api_key(api_key)
    selected_specialists = select_specialists(
        meeting_record["text"],
        enabled_specialists,
    )
    system_instruction = build_system_instruction(selected_specialists)
    issue_catalog = build_issue_catalog(stored_issues)
    analysis_prompt = build_analysis_prompt(meeting_record, issue_catalog)
    if analysis_depth == "standard":
        analysis_prompt += "\n\nUse concise analysis and include only material issues."
    else:
        analysis_prompt += "\n\nUse detailed analysis while excluding routine administrative content."
    gemini_client = genai.Client(api_key=resolved_api_key)
    try:
        generation_response = gemini_client.models.generate_content(
            model=model_name,
            contents=analysis_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=MeetingAnalysis,
                temperature=0.1,
                max_output_tokens=32768,
            ),
        )
    finally:
        gemini_client.close()

    parsed_response = generation_response.parsed
    if isinstance(parsed_response, MeetingAnalysis):
        meeting_analysis = parsed_response
    elif parsed_response is not None:
        meeting_analysis = MeetingAnalysis.model_validate(parsed_response)
    else:
        meeting_analysis = MeetingAnalysis.model_validate_json(generation_response.text)
    meeting_analysis.meeting_id = meeting_record["meeting_id"]
    meeting_analysis.meeting_date = meeting_record.get("meeting_date")
    return meeting_analysis, read_usage_metadata(generation_response)


def test_gemini_connection(api_key: str | None, model_name: str) -> str:
    """Verify Gemini access and the configured model."""
    resolved_api_key = resolve_api_key(api_key)
    gemini_client = genai.Client(api_key=resolved_api_key)
    try:
        model_record = gemini_client.models.get(model=model_name)
    finally:
        gemini_client.close()
    return getattr(model_record, "display_name", None) or model_name

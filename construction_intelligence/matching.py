import re
import unicodedata
from collections import Counter

from construction_intelligence.models import ExtractedIssue


STOP_WORDS = {
    "and",
    "the",
    "for",
    "with",
    "from",
    "this",
    "that",
    "issue",
    "works",
    "work",
    "system",
    "project",
    "construction",
}


def normalize_text(value: str | None) -> str:
    """Normalize issue text for deterministic comparison."""
    normalized_value = unicodedata.normalize("NFKD", value or "")
    ascii_value = normalized_value.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", ascii_value.lower()).strip()


def tokenize_text(value: str | None) -> set[str]:
    """Convert normalized text into useful comparison tokens."""
    return {
        token
        for token in normalize_text(value).split()
        if len(token) > 2 and token not in STOP_WORDS
    }


def token_similarity(left_value: str | None, right_value: str | None) -> float:
    """Calculate Jaccard similarity between two text values."""
    left_tokens = tokenize_text(left_value)
    right_tokens = tokenize_text(right_value)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def field_similarity(left_value: str | None, right_value: str | None) -> float:
    """Compare a structured issue field."""
    normalized_left = normalize_text(left_value)
    normalized_right = normalize_text(right_value)
    if not normalized_left or not normalized_right:
        return 0.0
    if normalized_left == normalized_right:
        return 1.0
    return token_similarity(normalized_left, normalized_right)


def calculate_issue_similarity(extracted_issue: ExtractedIssue, stored_issue: dict) -> float:
    """Calculate a weighted similarity score for issue matching."""
    stored_assessment = stored_issue.get("current_assessment", {})
    weighted_scores = [
        (token_similarity(extracted_issue.title, stored_issue.get("title")), 0.30),
        (field_similarity(extracted_issue.discipline, stored_issue.get("discipline")), 0.15),
        (field_similarity(extracted_issue.category, stored_issue.get("category")), 0.10),
        (field_similarity(extracted_issue.system, stored_assessment.get("system")), 0.15),
        (field_similarity(extracted_issue.component, stored_assessment.get("component")), 0.15),
        (field_similarity(extracted_issue.location, stored_assessment.get("location")), 0.10),
        (token_similarity(extracted_issue.summary, stored_assessment.get("summary")), 0.05),
    ]
    available_weights = sum(weight for score, weight in weighted_scores if score > 0)
    if available_weights == 0:
        return 0.0
    return sum(score * weight for score, weight in weighted_scores) / available_weights


def find_candidate_issues(
    extracted_issue: ExtractedIssue,
    stored_issues: dict[str, dict],
    maximum_candidates: int = 5,
) -> list[dict]:
    """Return the strongest deterministic candidate matches."""
    candidate_matches = []
    for issue_id, stored_issue in stored_issues.items():
        similarity_score = calculate_issue_similarity(extracted_issue, stored_issue)
        if similarity_score >= 0.25:
            candidate_matches.append(
                {
                    "issue_id": issue_id,
                    "title": stored_issue.get("title"),
                    "discipline": stored_issue.get("discipline"),
                    "category": stored_issue.get("category"),
                    "status": stored_issue.get("status"),
                    "similarity": round(similarity_score, 4),
                }
            )
    return sorted(
        candidate_matches,
        key=lambda candidate: candidate["similarity"],
        reverse=True,
    )[:maximum_candidates]


def choose_issue_prefix(category: str, discipline: str) -> str:
    """Choose a stable issue identifier prefix."""
    normalized_category = normalize_text(category)
    normalized_discipline = normalize_text(discipline)
    if "commercial" in normalized_category or "contract" in normalized_category:
        return "COM"
    if "programme" in normalized_category or "procurement" in normalized_category:
        return "PROG"
    if "quality" in normalized_category or "quality" in normalized_discipline:
        return "QUAL"
    return "TECH"


def generate_issue_id(stored_issues: dict[str, dict], prefix: str) -> str:
    """Generate the next issue identifier within a category."""
    existing_numbers = []
    for issue_id in stored_issues:
        issue_match = re.fullmatch(rf"{re.escape(prefix)}-(\d+)", issue_id)
        if issue_match:
            existing_numbers.append(int(issue_match.group(1)))
    next_number = max(existing_numbers, default=0) + 1
    return f"{prefix}-{next_number:03d}"


def count_issue_statuses(stored_issues: dict[str, dict]) -> Counter:
    """Count current issue statuses for dashboard indicators."""
    return Counter(issue.get("status", "unknown") for issue in stored_issues.values())


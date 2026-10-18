from typing import Literal

from pydantic import BaseModel, Field


IssueStatus = Literal[
    "identified",
    "under_review",
    "blocked",
    "action_agreed",
    "implementation_reported",
    "verification_pending",
    "closed_verified",
    "superseded",
    "unknown",
]

EvidenceType = Literal[
    "documented_statement",
    "party_reported_claim",
    "disputed_matter",
    "ai_inference",
    "verified_conclusion",
]

Significance = Literal["low", "medium", "high", "critical"]


class SourceEvidence(BaseModel):
    source_page: int | None = None
    passage: str
    evidence_type: EvidenceType
    speaker_role: str | None = None


class ExtractedDecision(BaseModel):
    decision: str
    authority: str | None = None
    deadline: str | None = None
    source_evidence: list[SourceEvidence] = Field(default_factory=list)


class ExtractedContradiction(BaseModel):
    subject: str
    positions: list[str] = Field(default_factory=list)
    source_evidence: list[SourceEvidence] = Field(default_factory=list)


class ExtractedIssue(BaseModel):
    title: str
    discipline: str
    category: str
    system: str | None = None
    component: str | None = None
    location: str | None = None
    summary: str
    status: IssueStatus
    significance: Significance
    approval_status: str | None = None
    evidence_status: str
    responsible_roles: list[str] = Field(default_factory=list)
    requested_actions: list[str] = Field(default_factory=list)
    deadlines: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    technical_implications: list[str] = Field(default_factory=list)
    commercial_implications: list[str] = Field(default_factory=list)
    programme_implications: list[str] = Field(default_factory=list)
    quality_implications: list[str] = Field(default_factory=list)
    contractual_position: str | None = None
    recommended_verification: str
    possible_existing_issue_id: str | None = None
    match_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_evidence: list[SourceEvidence] = Field(default_factory=list)


class MeetingAnalysis(BaseModel):
    meeting_id: str
    meeting_date: str | None = None
    summary: str
    issues: list[ExtractedIssue] = Field(default_factory=list)
    decisions: list[ExtractedDecision] = Field(default_factory=list)
    contradictions: list[ExtractedContradiction] = Field(default_factory=list)


class ValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


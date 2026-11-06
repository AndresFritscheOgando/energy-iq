"""Response contracts for documents. Never carries a storage key or parser output."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

DocumentState = Literal["uploaded", "processing", "needs_review", "failed", "deleted"]
RunState = Literal["queued", "running", "succeeded", "failed"]


class RunOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    run_number: int
    state: RunState
    attempts: int
    error_code: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None


class ProposedFieldOut(BaseModel):
    """One proposed value with where it was read. Never a confirmed value."""

    model_config = ConfigDict(frozen=True)

    name: str
    state: Literal["explicit", "inferred", "not_found"]
    value: str | None
    quote: str | None
    page_number: int | None
    uncertainty: str | None
    issues: list[str]
    evidence_verified: bool


class CandidateOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: str | None
    raw_value: str | None
    quote: str | None
    page_number: int | None
    evidence_verified: bool
    issues: list[str]


class ContradictionOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    field: str
    candidates: list[CandidateOut]


class ProposalConflictOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    fields: list[str]


class ProposalOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    fields: list[ProposedFieldOut]
    contradictions: list[ContradictionOut]
    conflicts: list[ProposalConflictOut]
    requires_review: Literal[True]


class ExtractionOut(BaseModel):
    """A run that produced a proposal. Prompts and page text are not returned."""

    model_config = ConfigDict(frozen=True)

    run_id: UUID
    run_number: int
    model: str | None
    prompt_version: str | None
    finished_at: str | None
    proposal: ProposalOut


class DocumentOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    meter_id: UUID
    state: DocumentState
    reason_code: str | None
    size_bytes: int
    sha256: str
    created_at: str
    deleted_at: str | None
    run: RunOut | None

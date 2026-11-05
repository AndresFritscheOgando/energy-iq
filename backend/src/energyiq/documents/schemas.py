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

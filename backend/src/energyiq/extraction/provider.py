"""Provider interface, limits, and the run loop (spec 0012/0004 AC-1, AC-4, AC-5).

A provider turns bounded page text into raw JSON text. This module owns
everything around it: input bounds, output bounds, JSON and schema checks,
bounded retries for transient failures, and run metadata. Provider output never
reaches a caller unparsed, and no code path here touches an invoice.
"""

import json
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import ValidationError

from energyiq.documents.pdf_text import ParsedPage
from energyiq.extraction.schema import PROMPT_REVISION, SCHEMA_REVISION, Proposal
from energyiq.extraction.validate import ValidatedProposal, validate_proposal

# Safe error codes. These are the only strings stored or returned for a failure.
INPUT_TOO_LARGE = "extraction_input_too_large"
NO_TEXT = "extraction_no_text"
OUTPUT_TOO_LARGE = "extraction_output_too_large"
INVALID_JSON = "extraction_invalid_json"
INVALID_SCHEMA = "extraction_invalid_schema"
PROVIDER_TIMEOUT = "extraction_timeout"
PROVIDER_UNAVAILABLE = "extraction_unavailable"
MODEL_MISSING = "extraction_model_missing"
CANCELLED = "extraction_cancelled"
RETRYABLE = frozenset({PROVIDER_TIMEOUT, PROVIDER_UNAVAILABLE})


class ProviderError(Exception):
    """A failure with a safe code. The message never holds bill content."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE


@dataclass(frozen=True)
class ExtractionLimits:
    max_pages: int = 10
    max_text_bytes: int = 262_144
    max_output_bytes: int = 16_384
    max_attempts: int = 2
    retry_base_seconds: float = 0.5
    # Total time the run may spend on model calls; no new attempt starts past it.
    deadline_seconds: float | None = None

    def __post_init__(self) -> None:
        if min(self.max_pages, self.max_text_bytes, self.max_output_bytes) < 1:
            raise ValueError("limits must be positive")
        if not 1 <= self.max_attempts <= 3:
            raise ValueError("max_attempts must be 1 to 3")
        if self.deadline_seconds is not None and self.deadline_seconds <= 0:
            raise ValueError("deadline_seconds must be positive")


@dataclass(frozen=True)
class ExtractionRequest:
    pages: tuple[ParsedPage, ...]


@dataclass(frozen=True)
class RawOutput:
    text: str
    model: str
    model_digest: str | None = None
    token_count: int | None = None


class Provider(Protocol):
    """Local model adapter. Raises ``ProviderError`` and nothing else."""

    def generate(self, request: ExtractionRequest) -> RawOutput: ...


@dataclass(frozen=True)
class RunMetadata:
    """What a run records. No page text, no quotes, no values (AC-5)."""

    model: str | None
    model_digest: str | None
    prompt_revision: str
    schema_revision: str
    token_count: int | None
    elapsed_ms: int
    attempts: int
    error_code: str | None


@dataclass(frozen=True)
class ExtractionOutcome:
    """``needs_review`` carries a proposal; ``failed`` carries only a code.

    Both leave the document and the manual draft path untouched.
    """

    state: str
    metadata: RunMetadata
    proposal: ValidatedProposal | None = None
    errors: tuple[str, ...] = field(default_factory=tuple)


def build_request(
    pages: Sequence[ParsedPage], limits: ExtractionLimits
) -> ExtractionRequest:
    """Bound the input. Over a limit fails; text is never cut to fit."""
    if len(pages) > limits.max_pages:
        raise ProviderError(INPUT_TOO_LARGE)
    size = sum(len(p.normalized_text.encode("utf-8")) for p in pages)
    if size > limits.max_text_bytes:
        raise ProviderError(INPUT_TOO_LARGE)
    if not any(p.quality_code == "has_text" for p in pages):
        raise ProviderError(NO_TEXT)
    return ExtractionRequest(tuple(pages))


def parse_output(raw: RawOutput, limits: ExtractionLimits) -> Proposal:
    if len(raw.text.encode("utf-8")) > limits.max_output_bytes:
        raise ProviderError(OUTPUT_TOO_LARGE)
    try:
        data = json.loads(raw.text)
    except (ValueError, RecursionError):
        raise ProviderError(INVALID_JSON) from None
    try:
        return Proposal.model_validate(data)
    except ValidationError:
        raise ProviderError(INVALID_SCHEMA) from None


def run_extraction(
    provider: Provider,
    pages: Sequence[ParsedPage],
    limits: ExtractionLimits,
    *,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[], float] = random.random,
    clock: Callable[[], float] = time.monotonic,
    cancelled: Callable[[], bool] = lambda: False,
) -> ExtractionOutcome:
    """One bounded run. Only transient failures retry, up to ``max_attempts``.

    Invalid JSON, a bad schema, or an oversized answer is final: the model
    already answered, and asking again would only spend more time. The caller
    maps ``needs_review`` and ``failed`` onto the run row.
    """
    started = clock()
    attempts = 0
    model: str | None = None
    digest: str | None = None
    tokens: int | None = None

    def done(
        state: str, code: str | None, proposal: ValidatedProposal | None = None
    ) -> ExtractionOutcome:
        meta = RunMetadata(
            model,
            digest,
            PROMPT_REVISION,
            SCHEMA_REVISION,
            tokens,
            int((clock() - started) * 1000),
            attempts,
            code,
        )
        return ExtractionOutcome(state, meta, proposal, (code,) if code else ())

    try:
        request = build_request(pages, limits)
    except ProviderError as error:
        return done("failed", error.code)
    while True:
        if cancelled():
            return done("failed", CANCELLED)
        past = limits.deadline_seconds is not None and (
            clock() - started >= limits.deadline_seconds
        )
        if past and attempts > 0:
            return done("failed", PROVIDER_TIMEOUT)
        attempts += 1
        try:
            raw = provider.generate(request)
            model, digest, tokens = raw.model, raw.model_digest, raw.token_count
            proposal = parse_output(raw, limits)
        except ProviderError as error:
            if error.retryable and attempts < limits.max_attempts:
                sleep(limits.retry_base_seconds * (1 + jitter()))
                continue
            return done("failed", error.code)
        except Exception:  # noqa: BLE001 - the contract is ProviderError only
            # An adapter bug must end as a safe code, not leave the run
            # ``running`` until its lease lapses.
            return done("failed", PROVIDER_UNAVAILABLE)
        # A proposal that fails checks is still a proposal: show it for review.
        return done("needs_review", None, validate_proposal(proposal, request.pages))


@dataclass
class FakeProvider:
    """Deterministic provider for tests. Replays scripted outputs or errors."""

    script: list[RawOutput | ProviderError]
    calls: int = 0

    def generate(self, request: ExtractionRequest) -> RawOutput:
        step = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        if isinstance(step, ProviderError):
            raise step
        return step

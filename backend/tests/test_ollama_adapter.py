"""Ollama adapter against a local stub server, and the extraction settings.

No real model runs. The stub speaks just enough of Ollama's HTTP API to prove
the request shape, the safe error codes, and the response bounds.
"""

import json
import socket
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest
from pydantic import ValidationError

from energyiq.documents.pdf_text import ParsedPage, text_digest
from energyiq.extraction.ollama import BAD_REQUEST, OllamaProvider, build_messages
from energyiq.extraction.provider import (
    MODEL_MISSING,
    PROVIDER_TIMEOUT,
    PROVIDER_UNAVAILABLE,
    ExtractionLimits,
    ExtractionRequest,
    ProviderError,
    run_extraction,
)
from energyiq.platform.settings import Settings

TEXT = "EDESUR\nTotal a pagar: RD$ 3,456.78\n"
PAGE = ParsedPage(1, TEXT, "native", "has_text", text_digest(TEXT))
REQUEST = ExtractionRequest((PAGE,))


class Stub:
    """A one route fake Ollama; ``mode`` picks the behavior of ``/api/chat``."""

    def __init__(self) -> None:
        self.mode = "ok"
        self.chat_bodies: list[dict[str, Any]] = []
        self.digest_lookups = 0
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                return

            def _send(self, code: int, body: bytes) -> None:
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                stub.digest_lookups += 1
                tags = {"models": [{"name": "m1", "digest": "sha256:abc"}]}
                self._send(200, json.dumps(tags).encode())

            def do_POST(self) -> None:
                length = int(self.headers["Content-Length"])
                stub.chat_bodies.append(json.loads(self.rfile.read(length)))
                mode = stub.mode
                if mode == "missing":
                    self._send(404, b'{"error":"model not found"}')
                elif mode == "boom":
                    self._send(500, b"{}")
                elif mode == "bad4xx":
                    self._send(400, b"{}")
                elif mode == "redirect":
                    self.send_response(302)
                    self.send_header("Location", "http://127.0.0.1:1/x")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                elif mode == "huge":
                    self._send(
                        200, b'{"message":{"content":"' + b"a" * 2_000_000 + b'"}}'
                    )
                elif mode == "deep":
                    self._send(200, b"[" * 500000)
                elif mode == "notjson":
                    self._send(200, b"<html>")
                elif mode == "nocontent":
                    self._send(200, b'{"message":{}}')
                elif mode == "slow":
                    time.sleep(1.5)
                    self._send(200, b"{}")
                else:
                    reply = {
                        "message": {"content": '{"fields": {}}'},
                        "prompt_eval_count": 100,
                        "eval_count": 20,
                    }
                    self._send(200, json.dumps(reply).encode())

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


@pytest.fixture
def stub() -> Iterator[Stub]:
    server = Stub()
    yield server
    server.server.shutdown()
    server.server.server_close()


def provider(stub: Stub, timeout: float = 5) -> OllamaProvider:
    return OllamaProvider(stub.url, "m1", timeout)


def test_chat_request_is_structured_deterministic_and_non_streaming(stub: Stub) -> None:
    out = provider(stub).generate(REQUEST)
    body = stub.chat_bodies[0]
    assert body["model"] == "m1" and body["stream"] is False
    assert body["options"] == {"temperature": 0}
    assert body["format"]["properties"]["fields"]  # the Proposal JSON schema
    assert "RD$ 3,456.78" in body["messages"][1]["content"]
    assert (out.model, out.model_digest, out.token_count) == ("m1", "sha256:abc", 120)
    assert json.loads(out.text) == {"fields": {}}


def test_bill_text_is_framed_as_untrusted_data() -> None:
    system, user = build_messages(REQUEST)
    assert "untrusted data" in system["content"]
    assert user["content"].startswith("Bill text follows.\n=== PAGE 1 ===")


@pytest.mark.parametrize(
    ("mode", "code"),
    [
        ("missing", MODEL_MISSING),
        ("boom", PROVIDER_UNAVAILABLE),
        ("bad4xx", BAD_REQUEST),
        ("redirect", BAD_REQUEST),
        ("huge", BAD_REQUEST),
        ("notjson", BAD_REQUEST),
        ("nocontent", BAD_REQUEST),
    ],
)
def test_failures_map_to_safe_codes(stub: Stub, mode: str, code: str) -> None:
    stub.mode = mode
    with pytest.raises(ProviderError) as caught:
        provider(stub).generate(REQUEST)
    assert caught.value.code == code
    assert str(caught.value) == code  # no body text in the message


def test_a_slow_model_times_out(stub: Stub) -> None:
    stub.mode = "slow"
    with pytest.raises(ProviderError) as caught:
        provider(stub, timeout=0.2).generate(REQUEST)
    assert caught.value.code == PROVIDER_TIMEOUT


def test_a_closed_port_is_unavailable() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    gone = OllamaProvider(f"http://127.0.0.1:{port}", "m1", 10)
    with pytest.raises(ProviderError) as caught:
        gone.generate(REQUEST)
    assert caught.value.code == PROVIDER_UNAVAILABLE


def test_the_run_loop_retries_a_timeout_against_the_real_adapter(stub: Stub) -> None:
    stub.mode = "slow"
    outcome = run_extraction(
        provider(stub, timeout=0.2),
        [PAGE],
        ExtractionLimits(max_attempts=2),
        sleep=lambda _: None,
    )
    assert (outcome.state, outcome.errors) == ("failed", (PROVIDER_TIMEOUT,))
    assert outcome.metadata.attempts == 2


def test_the_run_loop_turns_a_stub_answer_into_a_reviewable_result(stub: Stub) -> None:
    outcome = run_extraction(provider(stub), [PAGE], ExtractionLimits())
    assert outcome.state == "needs_review" and outcome.proposal is not None
    assert outcome.metadata.token_count == 120


# Settings ------------------------------------------------------------------


def test_extraction_is_off_by_default_with_no_model() -> None:
    settings = Settings(env="test")
    assert settings.extraction_enabled is False and settings.ollama_model is None


def test_enabling_extraction_needs_a_model() -> None:
    with pytest.raises(ValidationError, match="ollama_model"):
        Settings(env="test", extraction_enabled=True, run_lease_seconds=200)


@pytest.mark.parametrize(
    "url",
    [
        "ftp://x",
        "http://user:pw@127.0.0.1:11434",
        "http://127.0.0.1:11434/api",
        "http://127.0.0.1:11434?x=1",
        "127.0.0.1:11434",
    ],
)
def test_the_ollama_url_must_be_a_plain_origin(url: str) -> None:
    with pytest.raises(ValidationError, match="ollama_base_url"):
        Settings(
            env="test",
            extraction_enabled=True,
            ollama_model="m1",
            ollama_base_url=url,
            run_lease_seconds=200,
        )


def test_the_lease_must_outlast_every_model_call() -> None:
    with pytest.raises(ValidationError, match="lease_too_short_for_model"):
        Settings(env="test", extraction_enabled=True, ollama_model="m1")
    ok = Settings(
        env="test",
        extraction_enabled=True,
        ollama_model="m1",
        run_lease_seconds=91 + 30,
    )
    assert ok.ollama_timeout_seconds == 30


@pytest.mark.parametrize(
    "field",
    [
        "ollama_timeout_seconds",
        "extraction_max_attempts",
        "extraction_max_output_bytes",
    ],
)
@pytest.mark.parametrize("value", [0, -1, 10**9])
def test_extraction_limits_reject_zero_negative_and_over_ceiling(
    field: str, value: int
) -> None:
    with pytest.raises(ValidationError, match=field):
        kwargs: dict[str, Any] = {field: value}
        Settings(env="test", **kwargs)


def test_a_deeply_nested_reply_is_a_safe_code_not_a_crash(stub: Stub) -> None:
    stub.mode = "deep"
    with pytest.raises(ProviderError) as caught:
        provider(stub).generate(REQUEST)
    assert caught.value.code == BAD_REQUEST


def test_the_digest_is_looked_up_once_per_provider(stub: Stub) -> None:
    adapter = provider(stub)
    adapter.generate(REQUEST)
    adapter.generate(REQUEST)
    assert stub.digest_lookups == 1


class Exploding:
    def generate(self, request: ExtractionRequest) -> Any:
        raise KeyError("adapter bug with private text 3456.78")


def test_an_adapter_bug_ends_as_a_safe_code() -> None:
    outcome = run_extraction(Exploding(), [PAGE], ExtractionLimits())
    assert (outcome.state, outcome.errors) == ("failed", (PROVIDER_UNAVAILABLE,))
    assert "3456" not in repr(outcome)


def test_no_new_attempt_starts_past_the_deadline() -> None:
    now = [0.0]

    class Slow:
        calls = 0

        def generate(self, request: ExtractionRequest) -> Any:
            self.calls += 1
            now[0] += 10  # each call takes ten seconds, then times out
            raise ProviderError(PROVIDER_TIMEOUT)

    slow = Slow()
    outcome = run_extraction(
        slow,
        [PAGE],
        ExtractionLimits(max_attempts=3, deadline_seconds=5),
        sleep=lambda _: None,
        clock=lambda: now[0],
    )
    assert slow.calls == 1 and outcome.errors == (PROVIDER_TIMEOUT,)


def test_a_zero_deadline_is_rejected() -> None:
    with pytest.raises(ValueError):
        ExtractionLimits(deadline_seconds=0)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:11434",
        "http://localhost:11434",
        "http://[::1]:11434",
        "http://10.1.2.3:11434",
        "http://192.168.1.5:11434",
        "http://ollama:11434",
    ],
)
def test_local_and_private_hosts_are_accepted(url: str) -> None:
    ok = Settings(
        env="test",
        extraction_enabled=True,
        ollama_model="m1",
        ollama_base_url=url,
        run_lease_seconds=200,
    )
    assert ok.ollama_allow_remote is False


@pytest.mark.parametrize(
    "url",
    ["https://api.example.com", "http://8.8.8.8:11434", "http://ollama.example.org"],
)
def test_a_remote_host_needs_an_explicit_opt_in(url: str) -> None:
    kwargs: dict[str, Any] = {
        "env": "test",
        "extraction_enabled": True,
        "ollama_model": "m1",
        "ollama_base_url": url,
        "run_lease_seconds": 200,
    }
    with pytest.raises(ValidationError, match="ollama_base_url_not_local"):
        Settings(**kwargs)
    assert Settings(**kwargs, ollama_allow_remote=True).ollama_allow_remote is True


def test_the_lease_budget_counts_the_digest_call_and_retry_pauses() -> None:
    # 30 s x 2 attempts + 5 s digest + 2 s pauses + 30 s margin = 97
    base: dict[str, Any] = {
        "env": "test",
        "extraction_enabled": True,
        "ollama_model": "m1",
    }
    with pytest.raises(ValidationError, match="lease_too_short_for_model"):
        Settings(**base, run_lease_seconds=97)
    assert Settings(**base, run_lease_seconds=98).run_lease_seconds == 98


@pytest.mark.parametrize(
    "url",
    [
        "http://134744072:11434",  # 8.8.8.8 as one number
        "http://0x08080808:11434",  # the same, in hex
        "http://0177.0.0.1:11434",  # octal spelling
        "http://169.254.169.254",  # cloud metadata, link local
    ],
)
def test_odd_ip_spellings_and_link_local_are_not_local_hosts(url: str) -> None:
    kwargs: dict[str, Any] = {
        "env": "test",
        "extraction_enabled": True,
        "ollama_model": "m1",
        "ollama_base_url": url,
        "run_lease_seconds": 200,
    }
    with pytest.raises(ValidationError, match="ollama_base_url_not_local"):
        Settings(**kwargs)

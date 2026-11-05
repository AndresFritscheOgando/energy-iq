"""Client address and scheme behind the Next.js proxy (spec 0010 AC-14).

The test client's own peer is the string ``"testclient"``, not an IP, so
these tests pass explicit peers with ``TestClient(client=...)``.
"""

from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from energyiq.main import create_app
from energyiq.platform.http.csrf import CSRF_HEADER
from energyiq.platform.settings import Settings

PROBE = "/__probe"
LOGOUT = "/api/v1/auth/logout"


def _app(**overrides: Any) -> FastAPI:
    app = create_app(Settings(env="test", **overrides))

    @app.get(PROBE)
    def probe(request: Request) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        assert request.client is not None
        return {"host": request.client.host, "scheme": request.url.scheme}

    return app


def _seen(app: FastAPI, peer: str, headers: dict[str, str] | None = None) -> Any:
    client = TestClient(app, client=(peer, 50000))
    return client.get(PROBE, headers=headers or {}).json()


def test_untrusted_peer_forwarded_for_is_ignored() -> None:
    seen = _seen(_app(), "203.0.113.7", {"X-Forwarded-For": "198.51.100.1"})

    assert seen["host"] == "203.0.113.7"


def test_trusted_peer_yields_rightmost_untrusted_entry() -> None:
    seen = _seen(
        _app(), "127.0.0.1", {"X-Forwarded-For": "198.51.100.66, 198.51.100.1"}
    )

    assert seen["host"] == "198.51.100.1"


def test_trusted_hops_in_the_chain_are_skipped() -> None:
    app = _app(forwarded_allow_ips=["127.0.0.1", "10.0.0.0/8"])

    seen = _seen(app, "127.0.0.1", {"X-Forwarded-For": "198.51.100.1, 10.1.2.3"})

    assert seen["host"] == "198.51.100.1"


def test_ipv4_mapped_trusted_peer_is_trusted() -> None:
    seen = _seen(_app(), "::ffff:127.0.0.1", {"X-Forwarded-For": "198.51.100.1"})

    assert seen["host"] == "198.51.100.1"


def test_ipv4_mapped_peer_is_unmapped_without_forwarding() -> None:
    assert _seen(_app(), "::ffff:203.0.113.7")["host"] == "203.0.113.7"


def test_ipv6_loopback_peer_is_trusted() -> None:
    seen = _seen(_app(), "::1", {"X-Forwarded-For": "2001:db8::1"})

    assert seen["host"] == "2001:db8::1"


def test_empty_allow_list_trusts_nobody() -> None:
    app = _app(forwarded_allow_ips=[])

    seen = _seen(app, "127.0.0.1", {"X-Forwarded-For": "198.51.100.1"})

    assert seen["host"] == "127.0.0.1"


@pytest.mark.parametrize("proto", ["https,http", "https, http", "gopher", ""])
def test_junk_forwarded_proto_is_ignored(proto: str) -> None:
    seen = _seen(_app(), "127.0.0.1", {"X-Forwarded-Proto": proto})

    assert seen["scheme"] == "http"


def test_single_valid_forwarded_proto_from_trusted_peer_applies() -> None:
    seen = _seen(_app(), "127.0.0.1", {"X-Forwarded-Proto": "https"})

    assert seen["scheme"] == "https"


def test_untrusted_peer_cannot_set_the_scheme() -> None:
    seen = _seen(_app(), "203.0.113.7", {"X-Forwarded-Proto": "https"})

    assert seen["scheme"] == "http"


def _logout(app: FastAPI, headers: dict[str, str]) -> int:
    client = TestClient(app, client=("127.0.0.1", 50000), base_url="http://api.test")
    return client.post(LOGOUT, headers={CSRF_HEADER: "1", **headers}).status_code


@pytest.mark.parametrize("proto", ["https,http", "junk"])
def test_junk_forwarded_proto_cannot_break_the_origin_check(proto: str) -> None:
    """The own origin stays ``http://api.test``: a same origin request passes
    and a forged https origin is still refused."""
    app = _app(trusted_origins=[])
    proxied = {"X-Forwarded-Proto": proto}

    assert _logout(app, {**proxied, "Origin": "http://api.test"}) == 204
    assert _logout(app, {**proxied, "Origin": "https://api.test"}) == 403


def test_trusted_https_proto_moves_the_own_origin_to_https() -> None:
    app = _app(trusted_origins=[])
    proxied = {"X-Forwarded-Proto": "https"}

    assert _logout(app, {**proxied, "Origin": "https://api.test"}) == 204
    assert _logout(app, {**proxied, "Origin": "http://api.test"}) == 403

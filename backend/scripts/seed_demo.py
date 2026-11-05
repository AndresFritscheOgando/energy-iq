"""Fill a local account with synthetic readings (spec 0011 child 0003 AC-8 to AC-10).

Uses only the public API, so the demo can only contain data the product itself
can produce. The demo password is known and public, so before any request this
refuses anything but ``ENERGYIQ_ENV`` of ``dev`` or ``test`` and a loopback API.
Each run archives the account's properties and creates one fresh "Demo home",
so a rerun always ends the same way with dates near today.
"""

import argparse
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx2

DEMO_EMAIL = "demo@example.test"
DEFAULT_PASSWORD = "energyiq-demo-local-only"
DEFAULT_API_URL = "http://127.0.0.1:8000"
DEFAULT_APP_URL = "http://localhost:3000"
ZONE = "America/Santo_Domingo"
ALLOWED_ENVS = ("dev", "test")
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
HEADERS = {"X-EnergyIQ-CSRF": "1"}

# (days before today, cumulative kWh). Weekly from about 300 days ago, which
# leaves time before the first reading in the 365 day range. Days 200 to 158 is
# the six week stretch with no readings. The reading 70 days ago is lower than
# the one before it, so that span is an invalid interval, and later readings
# rise from the lower value. The last reading leaves a short stretch after it.
READINGS: tuple[tuple[int, str], ...] = (
    (300, "12400"),
    (293, "12462.5"),
    (286, "12519"),
    (279, "12583"),
    (272, "12641.25"),
    (265, "12702"),
    (258, "12768"),
    (251, "12825.5"),
    (244, "12889"),
    (237, "12947"),
    (230, "13011.75"),
    (223, "13072"),
    (216, "13130"),
    (209, "13196"),
    (200, "13270"),
    (158, "13642"),
    (151, "13705"),
    (144, "13761.5"),
    (137, "13824"),
    (130, "13887"),
    (123, "13946"),
    (116, "14009.25"),
    (109, "14068"),
    (102, "14130"),
    (95, "14191"),
    (88, "14253"),
    (81, "14312.5"),
    (77, "14351"),
    (70, "14290"),
    (63, "14349"),
    (56, "14411.5"),
    (49, "14470"),
    (42, "14533"),
    (35, "14594"),
    (28, "14652.75"),
    (21, "14716"),
    (14, "14775"),
    (7, "14838"),
    (3, "14872"),
)


class SeedError(Exception):
    """A failure with a clear message; the script exits nonzero and never retries."""


def check_target(api_url: str, env: Mapping[str, str]) -> None:
    """Runs before any request."""
    if env.get("ENERGYIQ_ENV") not in ALLOWED_ENVS:
        raise SeedError("Refusing to seed: set ENERGYIQ_ENV to dev or test.")
    if urlsplit(api_url).hostname not in LOOPBACK_HOSTS:
        raise SeedError(
            f"Refusing to seed {api_url}: the API URL host must be 127.0.0.1, "
            "localhost, or ::1, because the demo password is public."
        )


def today_local() -> date:
    return datetime.now(ZoneInfo(ZONE)).date()


def _problem_code(response: httpx2.Response) -> str:
    try:
        body: Any = response.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    return str(cast("dict[str, object]", body).get("code", ""))


def _fail_on_common(response: httpx2.Response, action: str) -> None:
    if response.status_code == 429:
        wait = response.headers.get("Retry-After", "a while")
        raise SeedError(
            f"Too many attempts while trying to {action}. Wait {wait} seconds and run this again."
        )
    if response.is_error:
        raise SeedError(
            f"Could not {action}: HTTP {response.status_code} {_problem_code(response)}".rstrip()
        )


def sign_in(client: httpx2.Client, password: str) -> None:
    credentials = {"email": DEMO_EMAIL, "password": password}
    login = client.post("/api/v1/auth/login", json=credentials)
    if login.status_code < 300:
        return
    if _problem_code(login) != "invalid_credentials":
        _fail_on_common(login, "sign in")
        return
    created = client.post("/api/v1/auth/register", json=credentials)
    if created.status_code == 409 and _problem_code(created) == "email_taken":
        raise SeedError(
            f"{DEMO_EMAIL} exists with a different password than the one set now. "
            "Use the password that made the account, or recreate the database "
            "(`docker compose down -v`, then migrate again)."
        )
    if created.status_code == 422:
        raise SeedError("ENERGYIQ_DEMO_PASSWORD must be 12 to 128 characters.")
    _fail_on_common(created, "register the demo account")


def archive_properties(client: httpx2.Client) -> None:
    cursor: str | None = None
    ids: list[str] = []
    while True:
        params = {"limit": 100, **({"cursor": cursor} if cursor else {})}
        page = client.get("/api/v1/properties", params=params)
        _fail_on_common(page, "list properties")
        body = page.json()
        ids.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    for property_id in ids:
        _fail_on_common(
            client.delete(f"/api/v1/properties/{property_id}"), "archive a property"
        )


def _post(client: httpx2.Client, path: str, body: dict[str, str], action: str) -> Any:
    response = client.post(path, json=body, headers={"Idempotency-Key": str(uuid4())})
    _fail_on_common(response, action)
    return response.json()


def create_demo(client: httpx2.Client, today: date) -> None:
    home = _post(
        client,
        "/api/v1/properties",
        {"nickname": "Demo home", "region": "Santo Domingo"},
        "create the property",
    )
    meter = _post(
        client,
        f"/api/v1/properties/{home['id']}/meters",
        {"label": "Main meter", "distributor": "EDESUR"},
        "create the meter",
    )
    for days_before, value in READINGS:
        _post(
            client,
            f"/api/v1/meters/{meter['id']}/readings",
            {
                "local_date": (today - timedelta(days=days_before)).isoformat(),
                "cumulative_kwh": value,
            },
            "save a reading",
        )


def run(
    argv: Sequence[str],
    env: Mapping[str, str],
    transport: httpx2.BaseTransport | None = None,
    today: Callable[[], date] = today_local,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--app-url", default=DEFAULT_APP_URL)
    args = parser.parse_args(argv)

    password = env.get("ENERGYIQ_DEMO_PASSWORD") or DEFAULT_PASSWORD
    try:
        check_target(args.api_url, env)
        with httpx2.Client(
            base_url=args.api_url,
            headers=HEADERS,
            transport=transport,
            trust_env=False,
            timeout=30,
        ) as client:
            sign_in(client, password)
            archive_properties(client)
            create_demo(client, today())
    except SeedError as error:
        print(str(error))
        return 1
    except httpx2.TransportError as error:
        print(f"Can't reach the API at {args.api_url}. ({type(error).__name__})")
        return 1
    print(f"Demo ready. Open {args.app_url}")
    print(f"Email: {DEMO_EMAIL}")
    print(f"Password: {password}")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:], os.environ))

"""Cross site request defense for cookie sessions (spec 0009/0002 AC-5).

Every unsafe method under ``/api/v1`` needs the custom header
``X-EnergyIQ-CSRF: 1``. A cross site form cannot set a custom header, and a
cross site ``fetch`` that sets one needs a CORS preflight this API never
grants with credentials. When the browser sends ``Origin``, it must also be
the request's own origin or a configured trusted origin; ``Origin: null``
(sandboxed frames, some redirects) is always rejected.

The check is a router level dependency, so it runs before the 415, 401, and
422 checks of each route. ``X-Forwarded-Host`` is never trusted: the own
origin is the scheme the app sees (``ForwardedClientMiddleware`` applies a
single valid ``X-Forwarded-Proto`` only from ``ENERGYIQ_FORWARDED_ALLOW_IPS``
peers) plus the ``Host`` header.
"""

from fastapi import Request

from energyiq.platform.http.dependencies import AppSettings
from energyiq.platform.http.problems import ProblemError

CSRF_HEADER = "X-EnergyIQ-CSRF"
CSRF_HEADER_VALUE = "1"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def own_origin(request: Request) -> str:
    """``scheme://host[:port]`` exactly as the client addressed this app."""
    host = request.headers.get("host", "")
    return f"{request.url.scheme}://{host}".lower()


def require_csrf(request: Request, settings: AppSettings) -> None:
    """403 ``csrf_rejected`` unless an unsafe request proves it is same site."""
    if request.method not in UNSAFE_METHODS:
        return
    if request.headers.get(CSRF_HEADER) != CSRF_HEADER_VALUE:
        raise ProblemError(403, "csrf_rejected")
    origin = request.headers.get("origin")
    if origin is None:
        return
    origin = origin.lower()
    if origin == "null":
        raise ProblemError(403, "csrf_rejected")
    if origin == own_origin(request) or origin in settings.trusted_origins:
        return
    raise ProblemError(403, "csrf_rejected")

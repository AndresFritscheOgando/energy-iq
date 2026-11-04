"""Route dependencies for HTTP conventions."""

from fastapi import Request

from energyiq.platform.http.problems import ProblemError


def is_json_media_type(content_type: str | None) -> bool:
    """True for ``application/json`` with at most ``charset=utf-8``."""
    if content_type is None:
        return False
    media_type, *parameters = content_type.split(";")
    if media_type.strip().lower() != "application/json":
        return False
    for parameter in parameters:
        name, separator, value = parameter.partition("=")
        if (
            not separator
            or name.strip().lower() != "charset"
            or value.strip().strip('"').lower() != "utf-8"
        ):
            return False
    return len(parameters) <= 1


async def require_json(request: Request) -> None:
    """Reject a body that is not JSON with 415 (spec 0008 AC-9).

    A dependency runs only after routing, so 404 and 405 keep precedence.
    """
    if not is_json_media_type(request.headers.get("content-type")):
        raise ProblemError(415, "unsupported_media_type")

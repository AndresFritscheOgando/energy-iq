"""RFC 9457 problem details: one error shape for every non 2xx response.

Clients branch on ``code``; ``detail`` is a fixed string per code and never
contains request values or exception text (spec 0008 AC-8).
"""

import json
from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import Scope

PROBLEM_MEDIA_TYPE = "application/problem+json"
MAX_VALIDATION_ERRORS = 100

ERROR_DETAILS: Mapping[str, str] = {
    "malformed_json": "The request body is not valid JSON.",
    "invalid_content_length": "The Content-Length header is invalid.",
    "not_found": "No resource exists at this path.",
    "method_not_allowed": "This method is not allowed for this path.",
    "payload_too_large": "The request body exceeds the size limit.",
    "unsupported_media_type": "The request body must be application/json.",
    "validation_error": "The request failed validation.",
    "duplicate_id": "Ids must be unique within readings and within events.",
    "reading_timestamp_conflict": (
        "Readings share a timestamp and must be resolved first."
    ),
    "internal_error": "An unexpected error occurred.",
    "database_unavailable": "The service is temporarily unavailable.",
    "schema_out_of_date": "The database schema is not up to date.",
    # Spec 0009/0002 (umbrella error catalog).
    "not_authenticated": "Authentication is required.",
    "invalid_credentials": "The email or password is incorrect.",
    "csrf_rejected": "The request failed cross site request checks.",
    "email_taken": "An account with this email already exists.",
    "property_name_taken": "A property with this nickname already exists.",
    "meter_label_taken": "An active meter with this label already exists.",
    "meter_inactive": "The meter is inactive.",
    "too_many_attempts": "Too many attempts. Try again later.",
}

VALIDATION_MESSAGES: Mapping[str, str] = {
    "missing": "Field is required.",
    "unknown_field": "Field is not allowed.",
    "invalid_type": "Value has the wrong JSON type.",
    "invalid_uuid": "Value must be a UUID string.",
    "invalid_kwh": (
        "Value must be a decimal string with at most 12 integer and 6 fraction digits."
    ),
    "invalid_datetime": "Value must be an ISO 8601 string with an explicit offset.",
    "datetime_out_of_range": "Value is outside the supported datetime range.",
    "invalid_enum": "Value is not one of the allowed options.",
    "too_many_items": "List exceeds its maximum length.",
    "window_order": "window.end must be after window.start.",
    "approval_pair": "approved_by and approved_at must be given together.",
    "invalid_value": "Value is invalid.",
    # Spec 0009/0002 (umbrella validation catalog).
    "invalid_email": "Value must be an email address.",
    "password_length": "Password must be 12 to 128 characters.",
    "invalid_timezone": "Value must be an IANA time zone name.",
    "invalid_text_length": "Text length is out of range.",
    "invalid_cursor": "Cursor is invalid.",
    "empty_patch": "Give at least one field to change.",
    "invalid_register_digits": "Value must be an integer from 4 to 9.",
}

_PYDANTIC_TYPES: Mapping[str, str] = {
    "missing": "missing",
    "extra_forbidden": "unknown_field",
    "string_type": "invalid_type",
    "int_type": "invalid_type",
    "float_type": "invalid_type",
    "bool_type": "invalid_type",
    "list_type": "invalid_type",
    "dict_type": "invalid_type",
    "model_type": "invalid_type",
    "model_attributes_type": "invalid_type",
    "uuid_type": "invalid_type",
    "datetime_type": "invalid_type",
    "uuid_parsing": "invalid_uuid",
    "uuid_version": "invalid_uuid",
    "string_pattern_mismatch": "invalid_kwh",
    "datetime_parsing": "invalid_datetime",
    "datetime_from_date_parsing": "invalid_datetime",
    "timezone_aware": "invalid_datetime",
    "enum": "invalid_enum",
    "literal_error": "invalid_enum",
    "too_long": "too_many_items",
}

_STATUS_CODES: Mapping[int, str] = {
    400: "malformed_json",
    404: "not_found",
    405: "method_not_allowed",
    413: "payload_too_large",
    415: "unsupported_media_type",
}


class ValidationErrorItem(BaseModel):
    """One located validation failure; never carries the submitted value."""

    model_config = ConfigDict(frozen=True)

    loc: list[str | int]
    code: str
    message: str


class Problem(BaseModel):
    """Problem details body (RFC 9457) with a stable ``code`` member."""

    model_config = ConfigDict(frozen=True)

    type: str = "about:blank"
    title: str
    status: int
    detail: str
    code: str
    request_id: str
    errors: list[ValidationErrorItem] | None = None
    errors_truncated: bool | None = None


class ProblemError(Exception):
    """Raised by routes and dependencies to answer with a problem response."""

    def __init__(
        self,
        status: int,
        code: str,
        extensions: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.extensions: Mapping[str, object] = extensions or {}
        self.headers: Mapping[str, str] = headers or {}


def request_id_from(scope: Scope) -> str:
    """The request id set by ``RequestContextMiddleware``, else a new one."""
    state: dict[str, Any] = scope.get("state") or {}
    request_id = state.get("request_id")
    return request_id if isinstance(request_id, str) else str(uuid4())


def problem_response(
    status: int,
    code: str,
    request_id: str,
    *,
    extensions: Mapping[str, object] | None = None,
    headers: Mapping[str, str] | None = None,
) -> Response:
    """Render a problem body; ``detail`` comes from the catalog only."""
    phrase = HTTPStatus(status).phrase
    body: dict[str, object] = {
        "type": "about:blank",
        "title": phrase,
        "status": status,
        "detail": ERROR_DETAILS.get(code, phrase),
        "code": code,
        "request_id": request_id,
    }
    body.update(extensions or {})
    return Response(
        content=json.dumps(body, ensure_ascii=False, separators=(",", ":")),
        status_code=status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=dict(headers) if headers else None,
    )


def problem_responses(
    model: type[BaseModel], statuses: Sequence[int]
) -> dict[int | str, dict[str, Any]]:
    """OpenAPI ``responses`` entries declaring ``model`` for each status."""
    return {
        status: {"model": model, "description": HTTPStatus(status).phrase}
        for status in statuses
    }


def _validation_code(error_type: str) -> str:
    if error_type in VALIDATION_MESSAGES:
        return error_type
    return _PYDANTIC_TYPES.get(error_type, "invalid_value")


def _is_malformed_body(errors: Sequence[Any]) -> bool:
    for error in errors:
        if error["type"] == "json_invalid":
            return True
        if error["type"] == "missing" and tuple(error["loc"]) == ("body",):
            return True
    return False


async def _handle_validation(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, RequestValidationError)
    request_id = request_id_from(request.scope)
    errors = exc.errors()
    if _is_malformed_body(errors):
        return problem_response(400, "malformed_json", request_id)
    items: list[dict[str, object]] = []
    for error in errors[:MAX_VALIDATION_ERRORS]:
        code = _validation_code(str(error["type"]))
        items.append(
            {
                "loc": list(error["loc"]),
                "code": code,
                "message": VALIDATION_MESSAGES[code],
            }
        )
    return problem_response(
        422,
        "validation_error",
        request_id,
        extensions={
            "errors": items,
            "errors_truncated": len(errors) > MAX_VALIDATION_ERRORS,
        },
    )


async def _handle_http(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, StarletteHTTPException)
    status = exc.status_code
    code = _STATUS_CODES.get(status, f"http_{status}")
    return problem_response(
        status, code, request_id_from(request.scope), headers=exc.headers
    )


async def _handle_problem(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, ProblemError)
    return problem_response(
        exc.status,
        exc.code,
        request_id_from(request.scope),
        extensions=exc.extensions,
        headers=exc.headers,
    )


def install_problem_handlers(app: FastAPI) -> None:
    """Register problem handlers. No ``Exception`` handler on purpose: the
    500 path belongs to ``RequestContextMiddleware`` (spec 0008)."""
    app.add_exception_handler(RequestValidationError, _handle_validation)
    app.add_exception_handler(StarletteHTTPException, _handle_http)
    app.add_exception_handler(ProblemError, _handle_problem)

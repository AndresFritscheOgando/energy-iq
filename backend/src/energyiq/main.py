"""FastAPI application factory.

Run with::

    uv run uvicorn energyiq.main:create_app --factory --app-dir backend/src --no-access-log

Middleware, outermost first: ``RequestContextMiddleware`` → ``CORSMiddleware``
(only when origins are configured) → ``BodySizeLimitMiddleware`` → routes.
"""

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from starlette.middleware.cors import CORSMiddleware

from energyiq import __version__
from energyiq.platform.http.health import router as health_router
from energyiq.platform.http.middleware import (
    REQUEST_ID_HEADER,
    BodySizeLimitMiddleware,
    RequestContextMiddleware,
)
from energyiq.platform.http.problems import (
    PROBLEM_MEDIA_TYPE,
    install_problem_handlers,
)
from energyiq.platform.logging import configure_logging
from energyiq.platform.settings import Settings
from energyiq.readings.api.router import router as readings_router


def _problem_media_types(schema: dict[str, Any]) -> dict[str, Any]:
    """Move error response schemas from ``application/json`` to problem+json."""
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            for status, response in operation.get("responses", {}).items():
                content = response.get("content", {})
                if str(status)[0] in "45" and "application/json" in content:
                    content[PROBLEM_MEDIA_TYPE] = content.pop("application/json")
    return schema


def _install_openapi(app: FastAPI) -> None:
    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            app.openapi_schema = _problem_media_types(
                get_openapi(
                    title=app.title,
                    version=app.version,
                    openapi_version=app.openapi_version,
                    description=app.description,
                    routes=app.routes,
                )
            )
        return app.openapi_schema

    app.openapi = openapi  # pyright: ignore[reportAttributeAccessIssue]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a new application; settings come from the environment when omitted.

    Invalid ``ENERGYIQ_*`` values raise a ``ValidationError`` naming the field.
    """
    if settings is None:
        settings = Settings()
    configure_logging(settings.log_level)

    docs = settings.env != "prod"
    app = FastAPI(
        title="EnergyIQ RD",
        version=__version__,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.settings = settings

    install_problem_handlers(app)
    app.include_router(health_router)
    app.include_router(readings_router)
    _install_openapi(app)

    # add_middleware puts each new layer outside the previous ones.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", REQUEST_ID_HEADER],
            expose_headers=[REQUEST_ID_HEADER],
            allow_credentials=False,
        )
    app.add_middleware(RequestContextMiddleware)
    return app

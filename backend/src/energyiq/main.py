"""FastAPI application factory.

Run with::

    uv run uvicorn energyiq.main:create_app --factory --app-dir backend/src         --no-access-log --no-proxy-headers

``--no-proxy-headers`` leaves the client address to
``ForwardedClientMiddleware`` and ``ENERGYIQ_FORWARDED_ALLOW_IPS`` alone.

Middleware, outermost first: ``ForwardedClientMiddleware`` →
``NoStoreMiddleware`` (``/api/v1/auth/``) → ``RequestContextMiddleware`` →
``CORSMiddleware`` (only when origins are configured) →
``BodySizeLimitMiddleware`` → routes.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware

from energyiq import __version__
from energyiq.identity.passwords import PasswordService
from energyiq.identity.router import router as identity_router
from energyiq.platform.db import (
    build_engine,
    install_database_handlers,
    script_head,
    session_factory,
)
from energyiq.platform.http.csrf import CSRF_HEADER
from energyiq.platform.http.health import router as health_router
from energyiq.platform.http.middleware import (
    REQUEST_ID_HEADER,
    BodySizeLimitMiddleware,
    ForwardedClientMiddleware,
    NoStoreMiddleware,
    RequestContextMiddleware,
)
from energyiq.platform.http.problems import (
    PROBLEM_MEDIA_TYPE,
    install_problem_handlers,
)
from energyiq.platform.http.ready import router as ready_router
from energyiq.platform.logging import configure_logging
from energyiq.platform.settings import Settings
from energyiq.properties.router import router as properties_router
from energyiq.readings.api.router import router as readings_router
from energyiq.readings.api.stored_router import router as stored_router

READINESS_POOL_TIMEOUT_SECONDS = 2
IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
IDEMPOTENT_REPLAYED_HEADER = "Idempotent-Replayed"
AUTH_PREFIX = "/api/v1/auth/"


def operation_id(route: APIRoute) -> str:
    """The route function name, so generated clients read ``login`` not
    ``login_api_v1_auth_login_post`` (spec 0010 AC-3). Names must be unique."""
    return route.name


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

    # Engines connect lazily: no database is needed to build the app.
    engine = build_engine(settings)
    readiness_engine = build_engine(
        settings, pool_size=1, pool_timeout=READINESS_POOL_TIMEOUT_SECONDS
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        try:
            yield
        finally:
            engine.dispose()
            readiness_engine.dispose()

    docs = settings.env != "prod"
    app = FastAPI(
        title="EnergyIQ RD",
        version=__version__,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
        lifespan=lifespan,
        generate_unique_id_function=operation_id,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory(engine)
    app.state.readiness_engine = readiness_engine
    app.state.schema_head = script_head()
    app.state.passwords = PasswordService(settings.env)

    install_problem_handlers(app)
    install_database_handlers(app)
    app.include_router(health_router)
    app.include_router(ready_router)
    app.include_router(identity_router)
    app.include_router(properties_router)
    app.include_router(readings_router)
    app.include_router(stored_router)
    _install_openapi(app)

    # add_middleware puts each new layer outside the previous ones.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=[
                "Content-Type",
                REQUEST_ID_HEADER,
                CSRF_HEADER,
                IDEMPOTENCY_KEY_HEADER,
            ],
            expose_headers=[
                REQUEST_ID_HEADER,
                "Retry-After",
                IDEMPOTENT_REPLAYED_HEADER,
            ],
            allow_credentials=False,
        )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(NoStoreMiddleware, prefixes=[AUTH_PREFIX])
    app.add_middleware(ForwardedClientMiddleware, trusted=settings.forwarded_allow_ips)
    return app

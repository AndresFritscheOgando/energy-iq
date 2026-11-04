"""The app's own route list, for matrices that must grow with the API (spec 0009/0004).

FastAPI 0.162 keeps included routers nested, so ``app.routes`` holds router
branches, not endpoints. ``iter_route_contexts`` is FastAPI's public walk over
the effective routes; their dependants include router level dependencies.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, iter_route_contexts

API_PREFIX = "/api/v1"
PUBLIC = frozenset(
    {
        f"{API_PREFIX}/auth/register",
        f"{API_PREFIX}/auth/login",
        f"{API_PREFIX}/auth/logout",
    }
)
UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True)
class ApiRoute:
    method: str
    path: str
    calls: frozenset[str]

    @property
    def key(self) -> tuple[str, str]:
        return (self.method, self.path)

    @property
    def has_id(self) -> bool:
        return "{" in self.path

    def needs(self, dependency: Callable[..., object]) -> bool:
        return dependency.__name__ in self.calls


def _calls(dependant: Dependant) -> Iterator[str]:
    for dependency in dependant.dependencies:
        yield getattr(dependency.call, "__name__", repr(dependency.call))
        yield from _calls(dependency)


def api_routes(app: FastAPI) -> list[ApiRoute]:
    """Every ``APIRoute`` method and path under ``/api/v1``, in app order."""
    routes: list[ApiRoute] = []
    for context in iter_route_contexts(app.routes):
        path = context.path or ""
        if not isinstance(context.original_route, APIRoute):
            continue
        if not path.startswith(API_PREFIX):
            continue
        calls = frozenset(_calls(context.dependant))
        routes.extend(
            ApiRoute(method, path, calls) for method in sorted(context.methods or ())
        )
    return routes

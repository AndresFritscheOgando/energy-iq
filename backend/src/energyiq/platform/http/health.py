"""Liveness endpoint; makes no database or network call."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from energyiq import __version__


class HealthResponse(BaseModel):
    """Body of ``GET /health``."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"]
    version: str


router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> HealthResponse:
    """Report that the process is serving requests, and its version."""
    return HealthResponse(status="ok", version=__version__)

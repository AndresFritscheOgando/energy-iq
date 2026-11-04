"""Fixtures for API tests against PostgreSQL (spec 0009/0002); see ``dbsupport``."""

from collections.abc import Callable
from typing import Any

import pytest
from dbsupport import CSRF, PASSWORD, Clock, Probe
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection

from energyiq.platform.clock import get_now


@pytest.fixture
def clock(db_app: FastAPI) -> Clock:
    frozen = Clock()
    db_app.dependency_overrides[get_now] = lambda: frozen.now
    return frozen


@pytest.fixture
def new_client(db_app: FastAPI, clock: Clock) -> Callable[[], TestClient]:
    """A fresh client (its own cookie jar) that sends the CSRF header."""

    def build() -> TestClient:
        return TestClient(db_app, headers=CSRF)

    return build


@pytest.fixture
def api(new_client: Callable[[], TestClient]) -> TestClient:
    return new_client()


Register = Callable[..., dict[str, Any]]


@pytest.fixture
def register() -> Register:
    """Register through the API and return the ``UserOut`` body."""

    def run(
        client: TestClient, email: str = "owner@example.test", password: str = PASSWORD
    ) -> dict[str, Any]:
        response = client.post(
            "/api/v1/auth/register", json={"email": email, "password": password}
        )
        assert response.status_code == 201, response.text
        return response.json()

    return run


@pytest.fixture
def owner(api: TestClient, register: Register) -> dict[str, Any]:
    """``api`` signed in as a registered owner."""
    return register(api)


@pytest.fixture
def probe(db_connection: Connection) -> Probe:
    return Probe(db_connection)

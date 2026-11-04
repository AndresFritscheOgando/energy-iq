"""The full ORM metadata, for Alembic and the schema tests."""

from importlib import import_module

from sqlalchemy import MetaData

from energyiq.platform.db import Base

MODEL_MODULES = (
    "energyiq.identity.models",
    "energyiq.platform.audit",
    "energyiq.properties.models",
    "energyiq.readings.persistence.rows",
)


def load_metadata() -> MetaData:
    """Import every ORM module so ``Base.metadata`` holds all tables."""
    for module in MODEL_MODULES:
        import_module(module)
    return Base.metadata

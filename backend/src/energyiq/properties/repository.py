"""Owner scoped queries for properties and meters (spec 0009 ownership rules).

Every function takes ``owner_id`` as a required positional parameter and
filters ``properties.owner_user_id = owner_id AND properties.archived_at IS
NULL`` in the same SQL statement. Not owned, archived, and nonexistent all
give ``None``, which routes turn into 404 ``not_found``.
"""

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Select, select, update
from sqlalchemy.orm import Session

from energyiq.platform.pagination import PageParams, keyset_page
from energyiq.properties.models import MeterRow, PropertyRow


def _owned_properties(owner_id: UUID) -> Select[PropertyRow]:
    return select(PropertyRow).where(
        PropertyRow.owner_user_id == owner_id, PropertyRow.archived_at.is_(None)
    )


def _owned_meters(owner_id: UUID) -> Select[MeterRow]:
    return (
        select(MeterRow)
        .join(PropertyRow, PropertyRow.id == MeterRow.property_id)
        .where(PropertyRow.owner_user_id == owner_id, PropertyRow.archived_at.is_(None))
    )


def get_property(
    session: Session, owner_id: UUID, property_id: UUID
) -> PropertyRow | None:
    return session.scalars(
        _owned_properties(owner_id).where(PropertyRow.id == property_id)
    ).one_or_none()


def list_properties(
    session: Session, owner_id: UUID, params: PageParams
) -> tuple[Sequence[PropertyRow], str | None]:
    return keyset_page(
        session,
        _owned_properties(owner_id),
        PropertyRow.created_at,
        PropertyRow.id,
        lambda row: (row.created_at, row.id),
        params,
    )


def update_property(
    session: Session,
    owner_id: UUID,
    property_id: UUID,
    values: Mapping[str, Any],
) -> PropertyRow | None:
    """One owner scoped ``UPDATE ... RETURNING``; ``None`` when not found."""
    return session.scalars(
        update(PropertyRow)
        .where(
            PropertyRow.id == property_id,
            PropertyRow.owner_user_id == owner_id,
            PropertyRow.archived_at.is_(None),
        )
        .values(**values)
        .returning(PropertyRow)
        .execution_options(synchronize_session=False)
    ).one_or_none()


def get_meter(session: Session, owner_id: UUID, meter_id: UUID) -> MeterRow | None:
    return session.scalars(
        _owned_meters(owner_id).where(MeterRow.id == meter_id)
    ).one_or_none()


def lock_meter(session: Session, owner_id: UUID, meter_id: UUID) -> MeterRow | None:
    """``SELECT ... FOR UPDATE OF meters`` by id and ownership only.

    ``active`` is not filtered here: the caller checks it after the lock, so
    a racing deactivate yields 409 ``meter_inactive``, never 404.
    """
    return session.scalars(
        _owned_meters(owner_id)
        .where(MeterRow.id == meter_id)
        .with_for_update(of=MeterRow)
        .execution_options(populate_existing=True)
    ).one_or_none()


def list_meters(
    session: Session,
    owner_id: UUID,
    property_id: UUID,
    *,
    include_inactive: bool,
    params: PageParams,
) -> tuple[Sequence[MeterRow], str | None]:
    statement = _owned_meters(owner_id).where(MeterRow.property_id == property_id)
    if not include_inactive:
        statement = statement.where(MeterRow.active)
    return keyset_page(
        session,
        statement,
        MeterRow.created_at,
        MeterRow.id,
        lambda row: (row.created_at, row.id),
        params,
    )

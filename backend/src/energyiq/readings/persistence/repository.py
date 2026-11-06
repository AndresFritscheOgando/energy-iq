"""Owner scoped stored reading and event queries."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from energyiq.platform.pagination import PageParams, keyset_page
from energyiq.properties.models import MeterRow, PropertyRow
from energyiq.readings.persistence.rows import MeterEventRow, ReadingRow


def property_timezone(session: Session, owner_id: UUID, meter_id: UUID) -> str | None:
    return session.scalar(
        select(PropertyRow.timezone)
        .join(MeterRow, MeterRow.property_id == PropertyRow.id)
        .where(
            MeterRow.id == meter_id,
            PropertyRow.owner_user_id == owner_id,
            PropertyRow.archived_at.is_(None),
        )
    )


def _readings(owner_id: UUID, meter_id: UUID) -> Select[ReadingRow]:
    return (
        select(ReadingRow)
        .join(MeterRow, MeterRow.id == ReadingRow.meter_id)
        .join(PropertyRow, PropertyRow.id == MeterRow.property_id)
        .where(
            MeterRow.id == meter_id,
            PropertyRow.owner_user_id == owner_id,
            PropertyRow.archived_at.is_(None),
        )
    )


def _events(owner_id: UUID, meter_id: UUID) -> Select[MeterEventRow]:
    return (
        select(MeterEventRow)
        .join(MeterRow, MeterRow.id == MeterEventRow.meter_id)
        .join(PropertyRow, PropertyRow.id == MeterRow.property_id)
        .where(
            MeterRow.id == meter_id,
            PropertyRow.owner_user_id == owner_id,
            PropertyRow.archived_at.is_(None),
        )
    )


def get_reading(
    session: Session, owner_id: UUID, meter_id: UUID, reading_id: UUID
) -> ReadingRow | None:
    return session.scalars(
        _readings(owner_id, meter_id).where(ReadingRow.id == reading_id)
    ).one_or_none()


def active_at(
    session: Session, owner_id: UUID, meter_id: UUID, at: datetime
) -> ReadingRow | None:
    return session.scalars(
        _readings(owner_id, meter_id).where(
            ReadingRow.recorded_at == at, ReadingRow.status != "voided"
        )
    ).one_or_none()


def list_readings(
    session: Session,
    owner_id: UUID,
    meter_id: UUID,
    params: PageParams,
    start: datetime | None,
    end: datetime | None,
    status: str | None,
    *,
    descending: bool = False,
) -> tuple[Sequence[ReadingRow], str | None]:
    query = _readings(owner_id, meter_id)
    if start is not None:
        query = query.where(ReadingRow.recorded_at >= start)
    if end is not None:
        query = query.where(ReadingRow.recorded_at < end)
    if status is not None:
        query = query.where(ReadingRow.status == status)
    return keyset_page(
        session,
        query,
        ReadingRow.recorded_at,
        ReadingRow.id,
        lambda row: (row.recorded_at, row.id),
        params,
        descending=descending,
    )


def get_event(
    session: Session, owner_id: UUID, meter_id: UUID, event_id: UUID
) -> MeterEventRow | None:
    return session.scalars(
        _events(owner_id, meter_id).where(MeterEventRow.id == event_id)
    ).one_or_none()


def list_events(
    session: Session,
    owner_id: UUID,
    meter_id: UUID,
    params: PageParams,
    status: str | None,
) -> tuple[Sequence[MeterEventRow], str | None]:
    query = _events(owner_id, meter_id)
    if status is not None:
        query = query.where(MeterEventRow.status == status)
    return keyset_page(
        session,
        query,
        MeterEventRow.effective_at,
        MeterEventRow.id,
        lambda row: (row.effective_at, row.id),
        params,
    )


def consumption_chain(
    session: Session,
    owner_id: UUID,
    meter_id: UUID,
    start: datetime,
    end: datetime,
) -> tuple[list[ReadingRow], list[MeterEventRow]]:
    base = _readings(owner_id, meter_id).where(ReadingRow.status != "voided")
    before = session.scalars(
        base.where(ReadingRow.recorded_at < start)
        .order_by(ReadingRow.recorded_at.desc(), ReadingRow.id.desc())
        .limit(1)
    ).all()
    middle = session.scalars(
        base.where(
            ReadingRow.recorded_at >= start, ReadingRow.recorded_at < end
        ).order_by(ReadingRow.recorded_at, ReadingRow.id)
    ).all()
    after = session.scalars(
        base.where(ReadingRow.recorded_at >= end)
        .order_by(ReadingRow.recorded_at, ReadingRow.id)
        .limit(1)
    ).all()
    readings = [*before, *middle, *after]
    if len(readings) == 1:
        lone = readings[0]
        following = session.scalars(
            base.where(ReadingRow.recorded_at > lone.recorded_at)
            .order_by(ReadingRow.recorded_at, ReadingRow.id)
            .limit(1)
        ).all()
        if following:
            readings.extend(following)
        else:
            preceding = session.scalars(
                base.where(ReadingRow.recorded_at < lone.recorded_at)
                .order_by(ReadingRow.recorded_at.desc(), ReadingRow.id.desc())
                .limit(1)
            ).all()
            readings = [*preceding, lone]
    events: list[MeterEventRow] = []
    if len(readings) >= 2:
        events = list(
            session.scalars(
                _events(owner_id, meter_id)
                .where(
                    MeterEventRow.status != "rejected",
                    MeterEventRow.effective_at > readings[0].recorded_at,
                    MeterEventRow.effective_at <= readings[-1].recorded_at,
                )
                .order_by(MeterEventRow.effective_at, MeterEventRow.id)
            ).all()
        )
    return readings, events

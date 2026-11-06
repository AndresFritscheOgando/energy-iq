"""Read published tariffs and write one as the maintenance command."""

from collections.abc import Sequence
from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from energyiq.tariffs.domain import (
    Distributor,
    Rounding,
    RoundingMode,
    RoundingScope,
    TariffBand,
    TariffSchedule,
)
from energyiq.tariffs.models import TariffBandRow, TariffScheduleRow


def _domain(row: TariffScheduleRow, bands: Sequence[TariffBandRow]) -> TariffSchedule:
    """Rebuild and revalidate a stored rule, so a bad row cannot price an invoice."""
    return TariffSchedule(
        distributor=Distributor(row.distributor),
        tariff_class="BTS-1",
        effective_start=row.effective_start,
        effective_end=row.effective_end,
        resolution_id=row.resolution_id,
        source_url=row.source_url,
        source_digest=row.source_digest,
        published_on=row.published_on,
        checked_on=row.checked_on,
        checked_by=row.checked_by,
        rounding=Rounding(
            places=row.rounding_places,
            mode=RoundingMode(row.rounding_mode),
            scope=RoundingScope(row.rounding_scope),
        ),
        bands=tuple(
            TariffBand.model_validate(
                {
                    "charge_type": band.charge_type,
                    "from_kwh": band.from_kwh,
                    "to_kwh": band.to_kwh,
                    "amount": band.amount,
                }
            )
            for band in sorted(bands, key=lambda item: item.position)
        ),
    )


def _load(session: Session, rows: Sequence[TariffScheduleRow]) -> list[TariffSchedule]:
    ids = [row.id for row in rows]
    grouped: dict[UUID, list[TariffBandRow]] = {id_: [] for id_ in ids}
    if ids:
        for band in session.scalars(
            select(TariffBandRow).where(TariffBandRow.schedule_id.in_(ids))
        ):
            grouped[band.schedule_id].append(band)
    return [_domain(row, grouped[row.id]) for row in rows]


def schedules_overlapping(
    session: Session, distributor: str, tariff_class: str, start: date, end: date
) -> list[TariffSchedule]:
    """Published rules for one scope that touch the inclusive date range."""
    rows = session.scalars(
        select(TariffScheduleRow)
        .where(
            TariffScheduleRow.distributor == distributor,
            TariffScheduleRow.tariff_class == tariff_class,
            TariffScheduleRow.effective_start <= end,
            TariffScheduleRow.effective_end >= start,
        )
        .order_by(TariffScheduleRow.effective_start)
    ).all()
    return _load(session, rows)


def find_by_resolution(
    session: Session, schedule: TariffSchedule
) -> TariffSchedule | None:
    row = session.scalars(
        select(TariffScheduleRow).where(
            TariffScheduleRow.distributor == schedule.distributor.value,
            TariffScheduleRow.tariff_class == schedule.tariff_class,
            TariffScheduleRow.resolution_id == schedule.resolution_id,
        )
    ).one_or_none()
    return _load(session, [row])[0] if row is not None else None


def overlapping_published(
    session: Session, schedule: TariffSchedule
) -> list[TariffSchedule]:
    return schedules_overlapping(
        session,
        schedule.distributor.value,
        schedule.tariff_class,
        schedule.effective_start,
        schedule.effective_end,
    )


def insert_published(
    session: Session, schedule: TariffSchedule, manifest_revision: str, now: datetime
) -> UUID:
    """Insert one rule and its bands as the next version for its scope."""
    version = (
        session.scalar(
            select(func.max(TariffScheduleRow.version)).where(
                TariffScheduleRow.distributor == schedule.distributor.value,
                TariffScheduleRow.tariff_class == schedule.tariff_class,
            )
        )
        or 0
    ) + 1
    schedule_id = uuid4()
    session.add(
        TariffScheduleRow(
            id=schedule_id,
            distributor=schedule.distributor.value,
            tariff_class=schedule.tariff_class,
            version=version,
            effective_start=schedule.effective_start,
            effective_end=schedule.effective_end,
            resolution_id=schedule.resolution_id,
            source_url=schedule.source_url,
            source_digest=schedule.source_digest,
            published_on=schedule.published_on,
            checked_on=schedule.checked_on,
            checked_by=schedule.checked_by,
            rounding_places=schedule.rounding.places,
            rounding_mode=schedule.rounding.mode.value,
            rounding_scope=schedule.rounding.scope.value,
            manifest_revision=manifest_revision,
            published_at=now,
        )
    )
    session.flush()
    for position, band in enumerate(schedule.bands):
        session.add(
            TariffBandRow(
                id=uuid4(),
                schedule_id=schedule_id,
                position=position,
                charge_type=band.charge_type.value,
                from_kwh=band.from_kwh,
                to_kwh=band.to_kwh,
                amount=band.amount,
            )
        )
    session.flush()
    return schedule_id

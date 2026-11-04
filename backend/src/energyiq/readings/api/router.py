"""``POST /api/v1/consumption/summary``: the Phase 1 domain over HTTP.

Spec 0009/0002 AC-10: the route now needs a session and the CSRF header; its
200 body is unchanged.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from energyiq.identity.dependencies import get_current_user
from energyiq.platform.clock import get_now
from energyiq.platform.http.csrf import require_csrf
from energyiq.platform.http.dependencies import require_json
from energyiq.platform.http.problems import ProblemError, problem_responses
from energyiq.readings import (
    compute_intervals,
    normalize_intervals,
    order_readings,
    summarize_consumption,
)
from energyiq.readings.api.mapping import (
    conflicts_out,
    find_duplicate_ids,
    to_domain,
    to_response,
)
from energyiq.readings.api.schemas import (
    ConsumptionProblem,
    ConsumptionSummaryRequest,
    ConsumptionSummaryResponse,
)

router = APIRouter(
    prefix="/api/v1", tags=["consumption"], dependencies=[Depends(require_csrf)]
)


@router.post(
    "/consumption/summary",
    dependencies=[Depends(require_json), Depends(get_current_user)],
    responses=problem_responses(
        ConsumptionProblem, (400, 401, 403, 413, 415, 422, 500, 503)
    ),
)
def consumption_summary(
    body: ConsumptionSummaryRequest,
    now: Annotated[datetime, Depends(get_now)],
) -> ConsumptionSummaryResponse:
    """Summarize posted readings and events over a window. Stores nothing.

    Stages run in a fixed order and the first failure answers: schema,
    duplicate ids, mapping, timestamp conflicts, then computation (AC-5a).
    """
    duplicates = find_duplicate_ids(body)
    if duplicates:
        raise ProblemError(
            422,
            "duplicate_id",
            {"duplicates": [item.model_dump(mode="json") for item in duplicates]},
        )

    readings, events = to_domain(body, now)

    order = order_readings(readings)
    if order.conflicts:
        raise ProblemError(
            422,
            "reading_timestamp_conflict",
            {
                "conflicts": [
                    item.model_dump(mode="json")
                    for item in conflicts_out(order.conflicts)
                ]
            },
        )

    intervals = compute_intervals(order, events)
    summary = summarize_consumption(
        intervals, body.meter_id, body.window.start, body.window.end
    )
    return to_response(summary, normalize_intervals(intervals))

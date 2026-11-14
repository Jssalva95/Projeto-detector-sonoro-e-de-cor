"""Approved dashboard query limits and additive response envelopes."""

from datetime import datetime, timedelta
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from app.models.enums import EventType, Severity
from app.schemas.domain import DataSchema, Identifier, UtcDateTime
from app.schemas.operational import OperationalMachine

Count = Annotated[int, Field(ge=0)]
Bucket = Literal['hour', 'day']
StatusFilter = Literal['NORMAL', 'FAULT', 'OFFLINE', 'MAINTENANCE', 'UNKNOWN']
MAX_BUCKETS = 200


def period_bounds(start: datetime, end: datetime, bucket: Bucket) -> list[tuple[datetime, datetime]]:
    """UTC-aligned, clipped half-open intervals; bounded even for extreme dates."""
    step = timedelta(hours=1) if bucket == 'hour' else timedelta(days=1)
    aligned = start.replace(minute=0, second=0, microsecond=0)
    if bucket == 'day':
        aligned = aligned.replace(hour=0)
    bounds: list[tuple[datetime, datetime]] = []
    current = start
    while current < end:
        if len(bounds) == MAX_BUCKETS:
            raise ValueError('Period exceeds 200 buckets')
        # Compare differences before adding, avoiding overflow near datetime.max.
        boundary = end if end - aligned <= step else aligned + step
        bounds.append((current, boundary))
        current = aligned = boundary
    return bounds


class PeriodFilters(DataSchema):
    start_date: UtcDateTime
    end_date: UtcDateTime
    bucket: Bucket
    machine_id: Identifier | None = None
    event_type: EventType | None = None
    severity: Severity | None = None

    @model_validator(mode='after')
    def valid_period(self) -> Self:
        if self.start_date >= self.end_date:
            raise ValueError('start_date must precede end_date')
        period_bounds(self.start_date, self.end_date, self.bucket)
        return self


class MachineStatusFilters(DataSchema):
    machine_id: Identifier | None = None
    status: StatusFilter | None = None
    limit: Annotated[int, Field(ge=1, le=200)] = 50
    offset: Annotated[int, Field(ge=0, le=9223372036854775807)] = 0


class DashboardSummary(DataSchema):
    as_of: UtcDateTime
    total_machines: Count
    normal: Count
    fault: Count
    offline: Count
    maintenance: Count
    unknown: Count
    critical_events_24h: Count


class PeriodItem(DataSchema):
    start: UtcDateTime
    end: UtcDateTime
    count: Count


class EventsByPeriod(DataSchema):
    as_of: UtcDateTime
    start_date: UtcDateTime
    end_date: UtcDateTime
    bucket: Bucket
    items: list[PeriodItem]


class MachineStatusPage(DataSchema):
    as_of: UtcDateTime
    total: Count
    limit: int
    offset: int
    items: list[OperationalMachine]

"""Read-only dashboard aggregation; no inferred transitions or alert side effects."""

from sqlalchemy.orm import Session

from app.repositories import dashboard as repository
from app.schemas.dashboard import (
    DashboardSummary, EventsByPeriod, MachineStatusFilters, MachineStatusPage,
    PeriodFilters, PeriodItem, period_bounds,
)
from app.services.operational import states_from_rows


def summary(session: Session) -> DashboardSummary:
    return DashboardSummary.model_validate(repository.summary(session))


def machine_status(session: Session, filters: MachineStatusFilters) -> MachineStatusPage:
    rows = repository.machine_status(session, filters)
    return MachineStatusPage(as_of=rows[0]['as_of'], total=rows[0]['total'],
                             limit=filters.limit, offset=filters.offset,
                             items=states_from_rows([row for row in rows if row['machine_id'] is not None]))


def events_by_period(session: Session, filters: PeriodFilters) -> EventsByPeriod:
    rows = repository.events_by_period(
        session, filters, period_bounds(filters.start_date, filters.end_date, filters.bucket),
    )
    return EventsByPeriod(as_of=rows[0]['as_of'], start_date=filters.start_date,
                          end_date=filters.end_date, bucket=filters.bucket,
                          items=[PeriodItem(start=row['start'], end=row['end'], count=row['count']) for row in rows])

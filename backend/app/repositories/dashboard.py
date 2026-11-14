"""One PostgreSQL statement/snapshot per response, with database-side pagination."""

from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import DateTime, and_, case, column, func, select, true, values
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import CTE

from app.models import Event
from app.repositories.operational import evidence_statement
from app.schemas.dashboard import MachineStatusFilters, PeriodFilters


def state_sources(machine_id: int | None = None) -> tuple[CTE, CTE]:
    evidence = evidence_statement(machine_id).order_by(None).cte('evidence')
    c = evidence.c
    # Count non-null device IDs: a machine with no device has one outer-join row.
    online = func.count(c.device_id).filter(c.connection_event_type == 'DEVICE_ONLINE') > 0
    offline = and_(func.count(c.device_id) > 0,
                   func.count(c.device_id) == func.count(c.device_id).filter(
                       c.connection_event_type == 'DEVICE_OFFLINE'))
    status = case(
        (c.registered_status == 'MAINTENANCE', 'MAINTENANCE'),
        (c.fault_event_type == 'FAULT_CONFIRMED', 'FAULT'),
        (offline, 'OFFLINE'),
        (and_(c.fault_event_type == 'FAULT_RECOVERED', online), 'NORMAL'),
        else_=None,
    ).label('operational_status')
    states = select(c.machine_id, status).group_by(
        c.machine_id, c.registered_status, c.fault_event_type,
    ).cte('states')
    return evidence, states


def summary(session: Session) -> RowMapping:
    _, states = state_sources()
    as_of = func.statement_timestamp()
    critical = select(func.count(Event.id)).where(
        Event.severity == 'CRITICAL', Event.started_at >= as_of - timedelta(hours=24),
        Event.started_at < as_of,
    ).scalar_subquery()
    statement = select(
        as_of.label('as_of'), func.count(states.c.machine_id).label('total_machines'),
        *(func.count().filter(states.c.operational_status == status).label(status.lower())
          for status in ('NORMAL', 'FAULT', 'OFFLINE', 'MAINTENANCE')),
        func.count().filter(states.c.operational_status.is_(None)).label('unknown'),
        critical.label('critical_events_24h'),
    ).select_from(states)
    return session.execute(statement).mappings().one()


def machine_status(session: Session, filters: MachineStatusFilters) -> Sequence[RowMapping]:
    evidence, states = state_sources(filters.machine_id)
    selected = select(states)
    if filters.status is not None:
        selected = selected.where(states.c.operational_status.is_(None) if filters.status == 'UNKNOWN'
                                  else states.c.operational_status == filters.status)
    filtered = selected.cte('filtered')
    page = select(filtered.c.machine_id).order_by(filtered.c.machine_id).limit(
        filters.limit).offset(filters.offset).cte('page')
    # Metadata survives an empty page (including offset beyond the last machine).
    metadata = select(func.statement_timestamp().label('as_of'),
                      func.count().label('total')).select_from(filtered).cte('metadata')
    details = select(evidence).join(page, page.c.machine_id == evidence.c.machine_id).cte('details')
    statement = select(metadata, details).select_from(metadata).outerjoin(details, true()).order_by(
        details.c.machine_id, details.c.device_id,
    )
    return session.execute(statement).mappings().all()


def events_by_period(session: Session, filters: PeriodFilters,
                     bounds: list[tuple[datetime, datetime]]) -> Sequence[RowMapping]:
    intervals = values(column('start', DateTime(timezone=True)), column('end', DateTime(timezone=True)),
                       name='intervals').data(bounds)
    conditions = [Event.started_at >= intervals.c.start, Event.started_at < intervals.c.end]
    for name in ('machine_id', 'event_type', 'severity'):
        value = getattr(filters, name)
        if value is not None:
            conditions.append(getattr(Event, name) == value)
    statement = select(
        func.statement_timestamp().label('as_of'), intervals.c.start, intervals.c.end,
        func.count(Event.id).label('count'),
    ).select_from(intervals).outerjoin(Event, and_(*conditions)).group_by(
        intervals.c.start, intervals.c.end,
    ).order_by(intervals.c.start)
    return session.execute(statement).mappings().all()

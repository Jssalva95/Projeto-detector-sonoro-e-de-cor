"""Event queries, unique insertion and acknowledgment row locking."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Event
from app.schemas.events import EventFilters, EventRequest


def by_id(session: Session, identifier: int, *, lock: bool = False) -> Event | None:
    statement = select(Event).where(Event.id == identifier)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return session.scalar(statement)


def by_uuid(session: Session, identifier: UUID) -> Event | None:
    return session.scalar(select(Event).where(Event.uuid == identifier))


def insert_if_absent(session: Session, payload: EventRequest) -> Event | None:
    statement = insert(Event).values(**payload.model_dump()).on_conflict_do_nothing(
        constraint="uq_events_uuid",
    ).returning(Event)
    return session.scalar(statement)


def list_events(session: Session, filters: EventFilters) -> list[Event]:
    statement = select(Event)
    for name in ("machine_id", "event_type", "severity", "acknowledged"):
        value = getattr(filters, name)
        if value is not None:
            statement = statement.where(getattr(Event, name) == value)
    if filters.start_date is not None:
        statement = statement.where(Event.started_at >= filters.start_date)
    if filters.end_date is not None:
        statement = statement.where(Event.started_at <= filters.end_date)
    statement = statement.order_by(Event.started_at.desc(), Event.id.desc())
    return list(session.scalars(statement.limit(filters.limit).offset(filters.offset)))

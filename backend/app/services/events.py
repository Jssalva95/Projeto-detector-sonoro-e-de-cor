"""Idempotent event ingestion and first-writer acknowledgment; no state inference."""

from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Event
from app.repositories import events as repository
from app.repositories.alerts import latest_fault_transition
from app.services.alerts import enqueue
from app.schemas.events import EventFilters, EventRequest
from app.services.equipment import Conflict, InactiveDevice, NotFound, get_device, get_machine


def same_occurrence(existing: Event, payload: EventRequest) -> Event:
    if any(getattr(existing, name) != value for name, value in payload.model_dump().items()):
        raise Conflict("Event UUID already exists with different occurrence data")
    return existing


def create(session: Session, payload: EventRequest) -> tuple[Event, bool]:
    try:
        with session.begin_nested():
            device = get_device(session, payload.device_id, lock=True)
            if not device.is_active:
                raise InactiveDevice("Device is inactive")
            existing = repository.by_uuid(session, payload.uuid)
            if existing is not None:
                return same_occurrence(existing, payload), False
            # All device writers for this machine share a lock before ID
            # allocation, keeping fault-cycle order equal to persistence order.
            get_machine(session, payload.machine_id, lock=True)
            if device.machine_id != payload.machine_id:
                raise Conflict("Device is not associated with this machine")
            previous_transition = latest_fault_transition(session, payload.machine_id)
            created = repository.insert_if_absent(session, payload)
            if created is not None:
                enqueue(session, created, previous_transition)
                return created, True
            # Another transaction inserted this UUID. READ COMMITTED sees it now.
            existing = repository.by_uuid(session, payload.uuid)
            if existing is None:
                raise Conflict("Concurrent event conflict; retry the request")
            return same_occurrence(existing, payload), False
    except IntegrityError as error:
        if getattr(error.orig, "sqlstate", None) == "23503":
            raise Conflict("Referenced record prevents this operation") from None
        raise


def get(session: Session, identifier: int, *, lock: bool = False) -> Event:
    event = repository.by_id(session, identifier, lock=lock)
    if event is None:
        raise NotFound("Event not found")
    return event


def acknowledge(session: Session, identifier: int, user_id: int) -> Event:
    try:
        with session.begin_nested():
            event = get(session, identifier, lock=True)
            if not event.acknowledged:
                event.acknowledged = True
                event.acknowledged_by = user_id
                event.acknowledged_at = datetime.now(timezone.utc)
                session.flush()
            return event
    except IntegrityError as error:
        if getattr(error.orig, "sqlstate", None) == "23503":
            raise Conflict("Referenced record prevents this operation") from None
        raise


def list_events(session: Session, filters: EventFilters) -> list[Event]:
    return repository.list_events(session, filters)

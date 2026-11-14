"""Typed equipment queries; locks serialize heartbeat and device reassociation."""

from typing import TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Device, Event, Machine

Equipment = TypeVar("Equipment", Machine, Device)


def list_all(session: Session, model: type[Equipment]) -> list[Equipment]:
    return list(session.scalars(select(model).order_by(model.id)))


def by_id(session: Session, model: type[Equipment], identifier: int,
          *, lock: bool = False) -> Equipment | None:
    statement = select(model).where(model.id == identifier)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return session.scalar(statement)


def device_by_uid(session: Session, uid: str) -> Device | None:
    return session.scalar(select(Device).where(Device.device_uid == uid).with_for_update())


def machine_by_serial(session: Session, serial_number: str) -> Machine | None:
    return session.scalar(select(Machine).where(Machine.serial_number == serial_number))


def latest_device_event_id(session: Session, device_id: int) -> int:
    """Caller holds the device lock shared by all event ingestion writers."""
    return session.scalar(select(func.coalesce(func.max(Event.id), 0)).where(Event.device_id == device_id))

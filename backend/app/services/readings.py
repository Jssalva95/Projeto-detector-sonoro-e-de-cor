"""Persist telemetry without deriving machine state, events or heartbeat."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import SensorReading
from app.repositories import readings as repository
from app.schemas.domain import SensorReadingCreate
from app.schemas.readings import ReadingFilters
from app.services.equipment import Conflict, InactiveDevice, NotFound, get_device, get_machine


def create(session: Session, payload: SensorReadingCreate) -> SensorReading:
    try:
        with session.begin_nested():
            # Same row lock as device PATCH/DELETE/heartbeat; held through commit.
            device = get_device(session, payload.device_id, lock=True)
            get_machine(session, payload.machine_id)
            if not device.is_active:
                raise InactiveDevice("Device is inactive")
            if device.machine_id != payload.machine_id:
                raise Conflict("Device is not associated with this machine")
            reading = SensorReading(**payload.model_dump())
            session.add(reading)
            session.flush()
    except IntegrityError as error:
        code = getattr(error.orig, "sqlstate", None)
        if code == "23505":
            raise Conflict("Reading UUID already exists") from None
        if code == "23503":
            raise Conflict("Referenced record prevents this operation") from None
        raise
    return reading


def get(session: Session, identifier: int) -> SensorReading:
    reading = repository.by_id(session, identifier)
    if reading is None:
        raise NotFound("Reading not found")
    return reading


def list_readings(session: Session, filters: ReadingFilters) -> list[SensorReading]:
    return repository.list_readings(session, filters)

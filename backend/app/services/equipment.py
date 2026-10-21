"""CRUD and heartbeat only: no state inference, ingestion, events or alerts."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Device, Machine
from app.repositories import equipment as repository
from app.schemas.domain import DeviceCreate, MachineCreate
from app.schemas.equipment import DeviceHeartbeatRequest, DeviceUpdate, MachineUpdate


class EquipmentError(ValueError):
    pass


class NotFound(EquipmentError):
    pass


class Conflict(EquipmentError):
    pass


class InactiveDevice(EquipmentError):
    pass


@contextmanager
def controlled_write(session: Session) -> Iterator[None]:
    try:
        with session.begin_nested():
            yield
            session.flush()
    except IntegrityError as error:
        code = getattr(error.orig, "sqlstate", None)
        if code == "23505":
            raise Conflict("serial_number or device_uid already exists") from None
        if code == "23503":
            raise Conflict("Referenced record prevents this operation") from None
        raise


def get_machine(session: Session, identifier: int, *, lock: bool = False) -> Machine:
    machine = repository.by_id(session, Machine, identifier, lock=lock)
    if machine is None:
        raise NotFound("Machine not found")
    return machine


def get_device(session: Session, identifier: int, *, lock: bool = False) -> Device:
    device = repository.by_id(session, Device, identifier, lock=lock)
    if device is None:
        raise NotFound("Device not found")
    return device


def list_machines(session: Session) -> list[Machine]:
    return repository.list_all(session, Machine)


def list_devices(session: Session) -> list[Device]:
    return repository.list_all(session, Device)


def create_machine(session: Session, payload: MachineCreate) -> Machine:
    with controlled_write(session):
        machine = Machine(**payload.model_dump())
        session.add(machine)
    return machine


def update_machine(session: Session, identifier: int, payload: MachineUpdate) -> Machine:
    with controlled_write(session):
        machine = get_machine(session, identifier, lock=True)
        for name, value in payload.model_dump(exclude_unset=True).items():
            setattr(machine, name, value)
    return machine


def delete_machine(session: Session, identifier: int) -> None:
    with controlled_write(session):
        session.delete(get_machine(session, identifier, lock=True))


def create_device(session: Session, payload: DeviceCreate) -> Device:
    with controlled_write(session):
        get_machine(session, payload.machine_id)
        device = Device(**payload.model_dump())
        session.add(device)
    return device


def update_device(session: Session, identifier: int, payload: DeviceUpdate) -> Device:
    with controlled_write(session):
        device = get_device(session, identifier, lock=True)
        if payload.machine_id is not None:
            get_machine(session, payload.machine_id)
        for name, value in payload.model_dump(exclude_unset=True).items():
            setattr(device, name, value)
    return device


def delete_device(session: Session, identifier: int) -> None:
    with controlled_write(session):
        session.delete(get_device(session, identifier, lock=True))


def heartbeat(session: Session, payload: DeviceHeartbeatRequest) -> Device:
    with controlled_write(session):
        device = repository.device_by_uid(session, payload.device_uid)
        if device is None:
            raise NotFound("Device not found")
        if not device.is_active:
            raise InactiveDevice("Device is inactive")
        machine = repository.machine_by_serial(session, payload.serial_number)
        if machine is None:
            raise NotFound("Machine not found")
        if machine.id != device.machine_id:
            raise Conflict("Device is not associated with this machine")
        device.last_seen_at = datetime.now(timezone.utc)
        if "firmware_version" in payload.model_fields_set:
            device.firmware_version = payload.firmware_version
    return device

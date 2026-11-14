"""Flat evidence rows from one PostgreSQL statement/snapshot, without ORM lazy loads."""

from collections.abc import Sequence

from sqlalchemy import Select, and_, select, true
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from app.models import Device, Event, Machine


def evidence_statement(machine_id: int | None = None) -> Select:
    columns = (Event.id, Event.uuid, Event.event_type, Event.started_at, Event.created_at)
    fault = (select(*columns).where(
        Event.machine_id == Machine.id,
        Event.event_type.in_(['FAULT_CONFIRMED', 'FAULT_RECOVERED']),
    ).order_by(Event.id.desc()).limit(1).correlate(Machine).lateral('fault'))
    connection = (select(*columns).where(
        Event.machine_id == Machine.id, Event.device_id == Device.id,
        Event.id > Device.status_event_id_floor,
        Event.event_type.in_(['DEVICE_ONLINE', 'DEVICE_OFFLINE']),
    ).order_by(Event.id.desc()).limit(1).correlate(Machine, Device).lateral('connection'))
    statement = select(
        Machine.id.label('machine_id'), Machine.name, Machine.serial_number,
        Machine.block, Machine.corridor, Machine.status.label('registered_status'),
        Device.id.label('device_id'), Device.last_seen_at,
        *(column.label('fault_' + column.key) for column in fault.c),
        *(column.label('connection_' + column.key) for column in connection.c),
    ).select_from(Machine).outerjoin(fault, true()).outerjoin(
        Device, and_(Device.machine_id == Machine.id, Device.is_active.is_(True)),
    ).outerjoin(connection, true()).order_by(Machine.id, Device.id)
    if machine_id is not None:
        statement = statement.where(Machine.id == machine_id)
    return statement


def evidence_rows(session: Session, machine_id: int | None = None) -> Sequence[RowMapping]:
    return session.execute(evidence_statement(machine_id)).mappings().all()

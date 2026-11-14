"""Approved last-known state, public compatibility and migration preservation."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event as sql_event, func, inspect, select, text, update
from sqlalchemy.exc import IntegrityError

from app.models import Alert, Device, Event, Machine, User
from app.models.enums import MachineStatus
from app.schemas.domain import DeviceCreate, DeviceRead
from app.schemas.equipment import DeviceHeartbeatRequest, DeviceUpdate, MachineUpdate
from app.schemas.events import EventRequest
from app.schemas.operational import Availability, StatusReason
from app.services import equipment, events, operational
from test_domain import db, records, status_migration
from test_equipment import client, admin, machine, device
from test_auth import settings, user


@pytest.fixture
def fleet(db):
    machines = [Machine(serial_number=f'state-{i}', name='Fixture', block='T', corridor='T',
                        status='NORMAL') for i in range(2)]
    db.add_all(machines)
    db.flush()
    devices = [equipment.create_device(db, DeviceCreate(machine_id=machines[0].id,
                device_uid=f'state-{i}', device_name='Fixture')) for i in range(2)]
    return machines, devices


def emit(db, machine, device, kind, **overrides):
    payload = EventRequest(**(dict(uuid=uuid4(), machine_id=machine.id, device_id=device.id,
        event_type=kind, severity='INFO', started_at='2026-11-14T12:00:00Z', message='Test only') | overrides))
    return events.create(db, payload)[0], payload


def state(db, machine):
    return operational.list_states(db, machine.id)[0]


def test_empty_unknown_no_inference_from_registered_status_or_heartbeat(db, fleet):
    machines, devices = fleet
    assert state(db, machines[1]).device_evidence == []
    for registered in ('NORMAL', 'FAULT', 'OFFLINE'):
        equipment.update_machine(db, machines[0].id, MachineUpdate(status=registered))
        equipment.heartbeat(db, DeviceHeartbeatRequest(device_uid=devices[0].device_uid,
                             serial_number=machines[0].serial_number, status='ONLINE'))
        result = state(db, machines[0])
        assert result.registered_status == registered
        assert result.operational_status is result.fault_active is None
        assert result.availability == 'UNKNOWN'
        assert result.device_evidence[0].last_seen_at is not None
    assert operational.list_states(db, 9223372036854775807) == []


def test_failure_recovery_and_maintenance_preserve_independent_dimensions(db, fleet):
    machines, devices = fleet
    for device in devices:
        emit(db, machines[0], device, 'DEVICE_OFFLINE')
    assert state(db, machines[0]).operational_status == 'OFFLINE'
    fault, _ = emit(db, machines[0], devices[0], 'FAULT_CONFIRMED')
    result = state(db, machines[0])
    assert result.operational_status == 'FAULT' and result.availability == 'OFFLINE'
    assert result.fault_evidence.event_id == fault.id
    equipment.update_machine(db, machines[0].id, MachineUpdate(status='MAINTENANCE'))
    result = state(db, machines[0])
    assert result.operational_status == 'MAINTENANCE' and result.fault_active is True
    # Another device can recover the same machine-level fault cycle.
    recovery, _ = emit(db, machines[0], devices[1], 'FAULT_RECOVERED',
                       started_at='2026-01-01T08:00:00-04:00')
    equipment.update_machine(db, machines[0].id, MachineUpdate(status='NORMAL'))
    assert state(db, machines[0]).operational_status == 'OFFLINE'
    emit(db, machines[0], devices[0], 'DEVICE_ONLINE')
    result = state(db, machines[0])
    assert result.operational_status == 'NORMAL' and result.fault_active is False
    assert result.fault_evidence.event_id == recovery.id
    assert result.fault_evidence.started_at == datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def test_multiple_devices_unknown_inactive_and_online_without_recovery(db, fleet):
    machines, devices = fleet
    emit(db, machines[0], devices[0], 'DEVICE_OFFLINE')
    assert state(db, machines[0]).availability == 'UNKNOWN'  # other device has no evidence
    equipment.update_device(db, devices[1].id, DeviceUpdate(is_active=False))
    result = state(db, machines[0])
    assert result.operational_status == 'OFFLINE' and len(result.device_evidence) == 1
    emit(db, machines[0], devices[0], 'DEVICE_ONLINE')
    result = state(db, machines[0])
    assert result.availability == 'ONLINE' and result.operational_status is None
    equipment.update_device(db, devices[0].id, DeviceUpdate(is_active=False))
    assert state(db, machines[0]).availability == 'UNKNOWN'


def test_reassociation_return_reactivation_and_replay_invalidate_old_evidence(db, fleet):
    machines, devices = fleet
    device = devices[0]
    online, payload = emit(db, machines[0], device, 'DEVICE_ONLINE')
    fault, _ = emit(db, machines[0], device, 'FAULT_CONFIRMED')
    assert device.status_event_id_floor == 0
    for target in (machines[1], machines[0]):
        equipment.update_device(db, device.id, DeviceUpdate(machine_id=target.id))
        assert device.status_event_id_floor == fault.id  # includes every event type
        assert state(db, target).availability == 'UNKNOWN'
    assert events.create(db, payload)[1] is False
    assert state(db, machines[0]).availability == 'UNKNOWN'
    assert state(db, machines[0]).fault_active is True  # machine fault isn't discarded
    recent, _ = emit(db, machines[0], device, 'DEVICE_ONLINE')
    assert state(db, machines[0]).availability == 'ONLINE'
    equipment.update_device(db, device.id, DeviceUpdate(is_active=False))
    equipment.update_device(db, device.id, DeviceUpdate(is_active=True))
    assert device.status_event_id_floor == recent.id
    assert state(db, machines[0]).availability == 'UNKNOWN'
    emit(db, machines[0], device, 'DEVICE_ONLINE')
    for change in (DeviceUpdate(device_name='Renamed'), DeviceUpdate(firmware_version='test'),
                   DeviceUpdate(machine_id=machines[0].id), DeviceUpdate(is_active=True)):
        equipment.update_device(db, device.id, change)
        assert device.status_event_id_floor == recent.id
    assert state(db, machines[0]).availability == 'ONLINE'
    assert online.machine_id == fault.machine_id == machines[0].id


def test_one_statement_without_side_effects_and_noncritical_events_ignored(db, fleet):
    machines, devices = fleet
    emit(db, machines[0], devices[0], 'FAULT_CONFIRMED')
    for kind in ('COLOR_RED', 'ALARM_SOUND'):
        emit(db, machines[0], devices[0], kind)
    reviewer = User(name='Reviewer', email='reviewer@example.invalid', password_hash='test-only', role='OPERATOR')
    db.add(reviewer)
    db.flush()
    fault_id = db.scalar(select(Event.id).where(Event.event_type == 'FAULT_CONFIRMED'))
    events.acknowledge(db, fault_id, reviewer.id)
    # Recognition/end metadata do not imply recovery.
    db.execute(update(Event).values(ended_at=datetime(2026, 11, 15, tzinfo=timezone.utc)))
    connection = db.connection()
    statements = []
    def count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    sql_event.listen(connection, 'before_cursor_execute', count)
    try:
        result = operational.list_states(db)
    finally:
        sql_event.remove(connection, 'before_cursor_execute', count)
    assert len(statements) == 1 and statements[0].lstrip().upper().startswith('SELECT')
    assert len(result) == 2 and result[0].fault_active is True
    assert db.scalar(select(func.count()).select_from(Alert)) == 0
    assert db.get(Machine, machines[0].id).status == 'NORMAL'


def test_migration_backfills_all_device_events_preserving_rows(db, records):
    machine, _, device, _, event, _, _ = records
    connection = db.connection()
    # Run only in the rollback-isolated fixture, never downgrade public data.
    with Operations.context(MigrationContext.configure(connection)):
        status_migration().downgrade()
        assert 'status_event_id_floor' not in {c['name'] for c in inspect(connection).get_columns('devices')}
        connection.execute(text("INSERT INTO devices (machine_id,device_uid,device_name) VALUES (:id,'legacy-empty','Legacy')"),
                           {'id': machine.id})
        status_migration().upgrade()
    db.expire_all()
    assert device.status_event_id_floor == event.id
    assert state(db, machine).availability == 'UNKNOWN'
    assert db.scalar(select(func.count()).select_from(Event)) == 1
    assert db.scalar(select(func.count()).select_from(Alert)) == 1
    columns = {c['name']: c for c in inspect(connection).get_columns('devices')}
    assert str(columns['status_event_id_floor']['type']) == 'BIGINT'
    assert not columns['status_event_id_floor']['nullable']
    assert db.scalar(select(Device.status_event_id_floor).where(Device.device_uid == 'legacy-empty')) == 0
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.execute(text('UPDATE devices SET status_event_id_floor = -1'))
    empty = equipment.create_device(db, DeviceCreate(machine_id=machine.id,
                    device_uid='after-migration', device_name='New'))
    assert empty.status_event_id_floor == 0


def test_floor_is_not_public_input_or_output(client, admin, db, machine, device):
    assert 'status_event_id_floor' not in device
    response = client.patch(f"/api/v1/devices/{device['id']}", headers=admin,
                            json={'status_event_id_floor': 100})
    assert response.status_code == 422
    assert 'status_event_id_floor' not in DeviceRead.model_validate(db.get(Device, device['id'])).model_dump()
    response = client.post('/api/v1/devices', headers=admin, json={
        'machine_id': machine['id'], 'device_uid': 'forbidden', 'device_name': 'Test',
        'status_event_id_floor': 0})
    assert response.status_code == 422


@pytest.mark.parametrize('registered,fault,connection,expected,reason', [
    ('MAINTENANCE', True, 'OFFLINE', 'MAINTENANCE', 'REGISTERED_MAINTENANCE'),
    ('NORMAL', True, 'UNKNOWN', 'FAULT', 'ACTIVE_FAULT'),
    ('FAULT', False, 'OFFLINE', 'OFFLINE', 'ALL_ACTIVE_DEVICES_OFFLINE'),
    ('OFFLINE', False, 'ONLINE', 'NORMAL', 'RECOVERED_AND_ONLINE'),
    ('NORMAL', None, 'ONLINE', None, 'INSUFFICIENT_EVIDENCE'),
    ('FAULT', False, 'UNKNOWN', None, 'INSUFFICIENT_EVIDENCE'),
])
def test_approved_priority_table(registered, fault, connection, expected, reason):
    assert operational.evaluate(MachineStatus(registered), fault, Availability(connection)) == (
        None if expected is None else MachineStatus(expected), StatusReason(reason))

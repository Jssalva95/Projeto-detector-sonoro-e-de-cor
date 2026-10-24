"""Transactional queue and fault cycles in isolated PostgreSQL schemas."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.alerts.config import AlertConfigurationError, queue_settings
from app.models import Alert, AlertRecipient, Device, Event, Machine
from app.repositories import alerts as repository
from app.schemas.events import EventRequest
from app.services import events
from test_auth import settings, user
from test_domain import db
from test_equipment import admin, client, device, machine
from test_events import payload, post
from test_event_concurrency import concurrent_database


@pytest.fixture
def policy(monkeypatch):
    monkeypatch.setenv('TELEGRAM_ENABLED', 'true')
    monkeypatch.setenv('EMAIL_ENABLED', 'true')
    monkeypatch.setenv('ALERT_COOLDOWN_SECONDS', '60')  # Test fixture, not deployment default.


@pytest.fixture
def recipients(db):
    rows = [AlertRecipient(name='Fixture', channel=c, destination=d, is_active=active)
            for c, d, active in [('EMAIL', 'fixture@example.invalid', True),
                                  ('TELEGRAM', '123', True), ('EMAIL', 'off@example.invalid', False),
                                  ('SMS', 'fixture', True), ('WHATSAPP', 'fixture', True)]]
    db.add_all(rows)
    db.flush()
    return rows


def alerts(db):
    return list(db.scalars(select(Alert).order_by(Alert.id)))


def transition(client, payload, event_type='FAULT_CONFIRMED', **changes):
    return post(client, payload, uuid=str(uuid4()), event_type=event_type, **changes)


def test_pending_roundtrip_replay_and_active_cycle(client, db, payload, recipients, policy):
    response = post(client, payload)
    assert response.status_code == 201
    db.expire_all()
    rows = alerts(db)
    assert {r.recipient_id for r in rows} == {recipients[0].id, recipients[1].id}
    assert all(r.event_id == response.json()['id'] and r.status == 'PENDING'
               and r.sent_at is None and r.error_message is None for r in rows)
    assert post(client, payload).status_code == 200
    assert post(client, payload, message='conflict').status_code == 409
    assert transition(client, payload).status_code == 201
    assert len(alerts(db)) == 2
    assert db.get(Machine, payload['machine_id']).status == 'MAINTENANCE'
    assert db.get(Device, payload['device_id']).last_seen_at is None


@pytest.mark.parametrize('event_type', ['COLOR_RED', 'ALARM_SOUND', 'FAULT_RECOVERED',
                                        'DEVICE_ONLINE', 'DEVICE_OFFLINE'])
def test_other_events_never_enqueue(client, db, payload, recipients, policy, event_type):
    assert transition(client, payload, event_type).status_code == 201
    assert alerts(db) == []


def test_disabled_channel_no_retroactive_queue(client, db, payload, recipients, monkeypatch):
    assert post(client, payload).status_code == 201
    monkeypatch.setenv('EMAIL_ENABLED', 'true')
    monkeypatch.setenv('ALERT_COOLDOWN_SECONDS', '0')
    assert post(client, payload).status_code == 200
    assert transition(client, payload).status_code == 201
    assert alerts(db) == []
    assert transition(client, payload, 'FAULT_RECOVERED').status_code == 201
    assert transition(client, payload).status_code == 201
    assert [r.channel for r in alerts(db)] == ['EMAIL']


def test_no_recipients_then_added_does_not_replay(client, db, payload, policy):
    assert post(client, payload).status_code == 201
    db.add(AlertRecipient(name='Late', channel='EMAIL', destination='late@example.invalid'))
    db.flush()
    assert transition(client, payload).status_code == 201
    assert alerts(db) == []


@pytest.mark.parametrize('status', ['PENDING', 'SENT', 'FAILED'])
def test_cooldown_per_recipient_and_status(client, db, payload, recipients, policy, monkeypatch, status):
    now = datetime(2026, 10, 24, tzinfo=timezone.utc)
    monkeypatch.setattr(repository, 'database_now', lambda session: now)
    assert post(client, payload).status_code == 201
    for row in alerts(db):
        row.status = status
    db.flush()
    assert transition(client, payload, 'FAULT_RECOVERED').status_code == 201
    now += timedelta(seconds=59)
    # New recipient is independent of earlier recipients' cooldown.
    late = AlertRecipient(name='Late', channel='EMAIL', destination='late@example.invalid')
    db.add(late)
    db.flush()
    assert transition(client, payload).status_code == 201
    assert len(alerts(db)) == 3 and alerts(db)[-1].recipient_id == late.id
    now += timedelta(seconds=1)
    # A suppressed cycle cannot enqueue later merely because cooldown expires.
    assert transition(client, payload).status_code == 201
    assert len(alerts(db)) == 3
    assert transition(client, payload, 'FAULT_RECOVERED').status_code == 201
    assert transition(client, payload).status_code == 201
    assert len(alerts(db)) == 5  # Original two eligible at exactly 60 seconds.


def test_persistence_order_not_sensor_time(client, db, payload, recipients, policy, monkeypatch):
    monkeypatch.setenv('ALERT_COOLDOWN_SECONDS', '0')
    assert post(client, payload).status_code == 201
    assert transition(client, payload, 'DEVICE_ONLINE').status_code == 201
    assert transition(client, payload).status_code == 201
    assert len(alerts(db)) == 2
    assert transition(client, payload, 'FAULT_RECOVERED', started_at='2000-01-01T00:00:00Z').status_code == 201
    assert transition(client, payload, started_at='1999-01-01T00:00:00Z').status_code == 201
    assert len(alerts(db)) == 4


def test_atomic_rollback_on_enqueue_failure(db, client, payload, recipients, policy, monkeypatch):
    original = repository.insert_pending
    def failing(session, event, recipient, now):
        original(session, event, recipient, now)
        session.flush()
        raise RuntimeError('test-only failure after insert')
    monkeypatch.setattr(repository, 'insert_pending', failing)
    with pytest.raises(RuntimeError, match='test-only'):
        events.create(db, EventRequest(**payload))
    assert db.scalar(select(func.count()).select_from(Event)) == 0
    assert alerts(db) == []
    monkeypatch.setattr(repository, 'insert_pending', original)
    assert post(client, payload).status_code == 201
    assert len(alerts(db)) == 2


@pytest.mark.parametrize('value', ['', '-1', 'nan', 'inf', 'not-a-number'])
def test_invalid_policy_rolls_back_http(client, db, payload, recipients, policy, monkeypatch, value):
    monkeypatch.setenv('ALERT_COOLDOWN_SECONDS', value)
    response = post(client, payload)
    assert response.status_code == 503
    assert response.json() == {'detail': 'Alert configuration unavailable'}
    assert alerts(db) == []
    assert db.scalar(select(func.count()).select_from(Event)) == 0


def test_disabled_policy_does_not_require_cooldown():
    assert queue_settings() == ((), 0.0)


@pytest.mark.parametrize('same_uuid', [False, True])
def test_concurrent_faults_queue_once(concurrent_database, policy, same_uuid):
    session_scope, values, (devices, _) = concurrent_database
    with session_scope() as session:
        session.add(AlertRecipient(name='Concurrent', channel='EMAIL', destination='fixture@example.invalid'))
    barrier = Barrier(2, timeout=10)
    def submit(index):
        data = values if same_uuid else values | {'uuid': uuid4(), 'device_id': devices[index]}
        with session_scope() as session:
            barrier.wait()
            return events.create(session, EventRequest(**data))[1]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit, i) for i in range(2)]
        results = [f.result(timeout=20) for f in futures]
    assert sum(results) == (1 if same_uuid else 2)
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(Alert)) == 1


def test_independent_machines(concurrent_database, policy):
    session_scope, values, _ = concurrent_database
    with session_scope() as session:
        session.add(AlertRecipient(name='Fixture', channel='EMAIL', destination='fixture@example.invalid'))
        other = Machine(serial_number='other', name='Other', block='Test', corridor='Test', status='NORMAL')
        device = Device(machine=other, device_uid='other', device_name='Other')
        session.add(device)
        session.flush()
        second = values | {'uuid': uuid4(), 'machine_id': other.id, 'device_id': device.id}
    for data in (values, second):
        with session_scope() as session:
            events.create(session, EventRequest(**data))
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(Alert)) == 2

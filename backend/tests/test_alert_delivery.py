"""Delivery across real transaction boundaries, with no external transports."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
import logging
import signal
from threading import Barrier
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, select, text

from app.alerts.base import ProviderError
from app.alerts.config import AlertConfigurationError, TelegramSettings, poll_interval
from app.alerts.message import render_message
from app.alerts.telegram import TelegramProvider
from app.alerts import admin, worker
from app.models import Alert, AlertRecipient, Event, Machine
from app.repositories import alert_delivery as repository
from app.schemas.domain import AlertRead
from app.schemas.events import EventRequest
from app.services import events
from app.services.alert_delivery import process_one
from app.services.alert_admin import AlertAdminError, add_recipient, retry, set_active
from test_domain import db, records, attempt_migration
from test_event_concurrency import concurrent_database


@pytest.fixture
def delivery_case(concurrent_database, monkeypatch):
    sessions, payload, _ = concurrent_database
    monkeypatch.setenv('EMAIL_ENABLED', 'true')
    monkeypatch.setenv('ALERT_COOLDOWN_SECONDS', '0')
    with sessions() as session:
        recipient = add_recipient(session, 'Test', 'EMAIL', 'fixture@example.invalid')
        event, _ = events.create(session, EventRequest(**payload))
        identifier = session.scalar(select(Alert.id))
        recipient_id, event_id = recipient.id, event.id
    return sessions, identifier, recipient_id, event_id


def read_attempt(case):
    sessions, identifier, _, _ = case
    with sessions() as session:
        return AlertRead.model_validate(session.get(Alert, identifier))


def test_success_commits_claim_before_transport(delivery_case):
    sessions, identifier, _, _ = delivery_case
    calls = []
    class Provider:
        async def send(self, message, destination):
            with sessions() as session:
                # Another physical connection sees the committed reservation,
                # and NOWAIT proves no row lock is held during network I/O.
                row = session.scalar(select(Alert).where(Alert.id == identifier).with_for_update(nowait=True))
                assert row.attempt_started_at and row.status == 'PENDING'
                assert row.sent_at is None
            calls.append((message, destination))
    assert asyncio.run(process_one({'EMAIL': Provider()}, sessions))
    result = read_attempt(delivery_case)
    assert result.status == 'SENT' and result.sent_at >= result.attempt_started_at
    assert result.error_message is None and len(calls) == 1
    assert calls[0][1] == 'fixture@example.invalid'
    assert 'ALERTA DE FALHA' in calls[0][0] and 'Não informado' in calls[0][0]
    assert not asyncio.run(process_one({'EMAIL': Provider()}, sessions))
    assert len(calls) == 1


@pytest.mark.parametrize('error,code', [
    (ProviderError('telegram_rejected'), 'telegram_rejected'),
    (ProviderError('email_rejected'), 'email_rejected'),
    (ProviderError('email_connection_failed'), 'email_connection_failed'),
    (ProviderError('email_tls_failed'), 'email_tls_failed'),
    (ProviderError('email_protocol_failed'), 'email_protocol_failed'),
    (ProviderError('email_auth_rejected'), 'email_auth_rejected'),
    (ProviderError('email_app_password_required'), 'email_app_password_required'),
    (ProviderError('email_auth_unavailable'), 'email_auth_unavailable'),
    (ProviderError('email_auth_connection_failed'), 'email_auth_connection_failed'),
    (ProviderError('delivery_unconfirmed'), 'delivery_unconfirmed'),
    (ProviderError('fake_secret'), 'delivery_unconfirmed'),
    (OSError('fake_secret'), 'delivery_unconfirmed'),
])
def test_failure_no_automatic_retry(delivery_case, error, code, caplog):
    sessions, *_ = delivery_case
    provider = AsyncMock()
    provider.send.side_effect = error
    with caplog.at_level(logging.INFO):
        assert asyncio.run(process_one({'EMAIL': provider}, sessions))
    row = read_attempt(delivery_case)
    assert row.status == 'FAILED' and row.error_message == code and row.sent_at is None
    assert row.attempt_started_at is not None
    assert not asyncio.run(process_one({'EMAIL': provider}, sessions))
    provider.send.assert_awaited_once()
    assert 'fake_secret' not in caplog.text


def test_cancel_after_claim_never_resumes(delivery_case):
    sessions, *_ = delivery_case
    provider = AsyncMock()
    provider.send.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(process_one({'EMAIL': provider}, sessions))
    row = read_attempt(delivery_case)
    assert row.status == 'PENDING' and row.attempt_started_at and row.sent_at is None
    assert not asyncio.run(process_one({'EMAIL': provider}, sessions))
    provider.send.assert_awaited_once()


@pytest.mark.parametrize('fail_transaction', [1, 2])
def test_commit_failure_never_repeats_external_call(delivery_case, fail_transaction):
    sessions, *_ = delivery_case
    count = 0
    @contextmanager
    def failing_sessions():
        nonlocal count
        count += 1
        with sessions() as session:
            yield session
            if count == fail_transaction:
                raise RuntimeError('simulated_commit_failure')
    provider = AsyncMock()
    with pytest.raises(RuntimeError, match='simulated_commit_failure'):
        asyncio.run(process_one({'EMAIL': provider}, failing_sessions))
    row = read_attempt(delivery_case)
    assert row.status == 'PENDING'
    assert (row.attempt_started_at is None) == (fail_transaction == 1)
    assert provider.send.await_count == (0 if fail_transaction == 1 else 1)
    worked = asyncio.run(process_one({'EMAIL': provider}, sessions))
    assert worked == (fail_transaction == 1)
    assert provider.send.await_count == 1


@pytest.mark.parametrize('change,code', [('inactive', 'recipient_inactive'),
    ('channel', 'recipient_channel_changed'), ('event', 'invalid_alert_event')])
def test_ineligible_attempt_does_not_send(delivery_case, change, code):
    sessions, _, recipient_id, event_id = delivery_case
    with sessions() as session:
        if change == 'inactive':
            set_active(session, recipient_id, False)
        elif change == 'channel':
            session.get(AlertRecipient, recipient_id).channel = 'TELEGRAM'
        else:
            session.get(Event, event_id).event_type = 'DEVICE_ONLINE'
    provider = AsyncMock()
    assert asyncio.run(process_one({'EMAIL': provider}, sessions))
    row = read_attempt(delivery_case)
    assert row.status == 'FAILED' and row.error_message == code
    provider.send.assert_not_awaited()


def test_disabled_channel_is_left_pending(delivery_case):
    sessions, *_ = delivery_case
    assert not asyncio.run(process_one({}, sessions))
    row = read_attempt(delivery_case)
    assert row.status == 'PENDING' and row.attempt_started_at is None


def test_concurrent_workers_claim_once(delivery_case):
    sessions, *_ = delivery_case
    barrier = Barrier(2, timeout=10)
    calls = []
    class Provider:
        async def send(self, message, destination):
            calls.append(destination)
    def work():
        barrier.wait()
        return asyncio.run(process_one({'EMAIL': Provider()}, sessions))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(work) for _ in range(2)]
        results = [f.result(timeout=20) for f in futures]
    assert sorted(results) == [False, True] and len(calls) == 1
    assert read_attempt(delivery_case).status == 'SENT'


def test_locked_row_is_skipped(delivery_case):
    sessions, identifier, *_ = delivery_case
    provider = AsyncMock()
    with sessions() as session:
        session.scalar(select(Alert).where(Alert.id == identifier).with_for_update())
        assert not asyncio.run(process_one({'EMAIL': provider}, sessions))
    provider.send.assert_not_awaited()
    assert asyncio.run(process_one({'EMAIL': provider}, sessions))


def test_manual_retry_retains_history_and_blocks_repeated_command(delivery_case):
    sessions, identifier, *_ = delivery_case
    provider = AsyncMock()
    provider.send.side_effect = ProviderError('delivery_unconfirmed')
    asyncio.run(process_one({'EMAIL': provider}, sessions))
    original = read_attempt(delivery_case)
    with sessions() as session:
        new = retry(session, identifier, accept_duplicate_risk=True)
        new_id = new.id
        assert new_id != identifier and new.status == 'PENDING' and new.attempt_started_at is None
    assert read_attempt(delivery_case) == original
    with pytest.raises(AlertAdminError, match='newer_attempt_exists'):
        with sessions() as session:
            retry(session, identifier, accept_duplicate_risk=True)
    provider.send.side_effect = None
    assert asyncio.run(process_one({'EMAIL': provider}, sessions))
    with sessions() as session:
        assert session.get(Alert, new_id).status == 'SENT'
        assert len(list(session.scalars(select(Alert)))) == 2


def test_uncertain_retry_requires_stopped_workers_and_explicit_risk(delivery_case):
    sessions, identifier, *_ = delivery_case
    with sessions() as session:
        repository.reserve(session, ('EMAIL',))  # Simulated crash after commit, before send.
    with pytest.raises(AlertAdminError, match='explicit_duplicate_risk'):
        with sessions() as session:
            retry(session, identifier, accept_duplicate_risk=False)
    with pytest.raises(AlertAdminError, match='stop_all_workers'):
        with sessions() as session:
            retry(session, identifier, accept_duplicate_risk=True)
    with sessions() as session:
        retry(session, identifier, accept_duplicate_risk=True, workers_stopped=True)
    assert read_attempt(delivery_case).error_message == 'delivery_unconfirmed'


@pytest.mark.parametrize('sent', [False, True])
def test_no_retry_for_sent_or_unstarted(delivery_case, sent):
    sessions, identifier, *_ = delivery_case
    if sent:
        asyncio.run(process_one({'EMAIL': AsyncMock()}, sessions))
    with pytest.raises(AlertAdminError, match='attempt_not_retryable'):
        with sessions() as session:
            retry(session, identifier, accept_duplicate_risk=True, workers_stopped=True)


def test_template_uses_occurrence_machine_and_actual_sensor_fields(db, records):
    machine, _, device, _, event, *_ = records
    machine.name = 'Original ç'
    other = Machine(serial_number='other', name='Other', block='B', corridor='C', status='NORMAL')
    device.machine = other
    db.flush()
    event.color, event.sound_detected = 'BLUE', False
    message = render_message(event, event.machine)
    assert 'Original ç' in message and 'Other' not in message
    assert 'AZUL' in message and 'NÃO DETECTADO' in message and '4095' in message
    assert str(event.uuid) in message and '+00:00' in message


def test_oversize_telegram_fails_without_truncation_or_network(delivery_case):
    sessions, identifier, recipient_id, event_id = delivery_case
    with sessions() as session:
        session.get(Alert, identifier).channel = 'TELEGRAM'
        recipient = session.get(AlertRecipient, recipient_id)
        recipient.channel, recipient.destination = 'TELEGRAM', '123'
        event = session.get(Event, event_id)
        session.get(Machine, event.machine_id).name = 'x' * 4096
    def handle(request):
        pytest.fail('Unexpected external call')
    provider = TelegramProvider(TelegramSettings(token='123:fake', timeout=1), transport=httpx.MockTransport(handle))
    assert asyncio.run(process_one({'TELEGRAM': provider}, sessions))
    assert read_attempt(delivery_case).error_message == 'invalid_message'


@pytest.mark.parametrize('value', ['', '0', '-1', 'nan', 'inf', 'bad'])
def test_poll_interval_requires_positive_explicit_value(monkeypatch, value):
    monkeypatch.setenv('ALERT_POLL_INTERVAL_SECONDS', value)
    with pytest.raises(AlertConfigurationError):
        poll_interval()


def test_poll_interval_configurable(monkeypatch):
    monkeypatch.setenv('ALERT_POLL_INTERVAL_SECONDS', '10')
    assert poll_interval() == 10


def test_migration_preserves_existing_alerts(db, records):
    attempt = records[-1]
    identifier = attempt.id
    connection = db.connection()
    with Operations.context(MigrationContext.configure(connection)):
        attempt_migration().downgrade()
        assert connection.scalar(text('SELECT count(*) FROM alerts')) == 1
        attempt_migration().upgrade()
    columns = {c['name']: c for c in inspect(connection).get_columns('alerts')}
    assert columns['attempt_started_at']['nullable'] and columns['attempt_started_at']['type'].timezone
    db.expire_all()
    row = db.get(Alert, identifier)
    assert row.attempt_started_at is None and row.status == 'PENDING'
    row.attempt_started_at = row.created_at
    db.flush()
    assert AlertRead.model_validate(row).attempt_started_at.utcoffset() == timedelta(0)


@pytest.mark.parametrize('channel,destination', [('SMS', 'fixture'), ('EMAIL', 'bad\r\naddress'),
                                               ('TELEGRAM', '123/path')])
def test_recipient_validation_no_insert(db, channel, destination):
    with pytest.raises(AlertAdminError):
        add_recipient(db, 'Fixture', channel, destination)
    assert list(db.scalars(select(AlertRecipient))) == []


def test_worker_graceful_stop_and_no_dispatch_when_disabled(delivery_case, monkeypatch):
    sessions, *_ = delivery_case
    monkeypatch.setenv('ALERT_POLL_INTERVAL_SECONDS', '0.01')
    monkeypatch.setattr(worker, 'configured_providers', lambda: {})
    monkeypatch.setattr(worker, 'session_scope', sessions)
    previous = signal.getsignal(signal.SIGTERM)
    calls = []
    async def work(providers):
        calls.append(providers)
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        return False
    monkeypatch.setattr(worker, 'process_one', work)
    asyncio.run(worker.run())
    assert calls == [{}] and signal.getsignal(signal.SIGTERM) == previous
    assert read_attempt(delivery_case).attempt_started_at is None


@pytest.mark.parametrize('sig', [signal.SIGINT, signal.SIGTERM])
def test_busy_worker_stops_after_current_item(monkeypatch, sig):
    @contextmanager
    def sessions():
        yield MagicMock()
    monkeypatch.setattr(worker, 'session_scope', sessions)
    monkeypatch.setattr(worker, 'configured_providers', lambda: {})
    monkeypatch.setenv('ALERT_POLL_INTERVAL_SECONDS', '0.01')
    previous = signal.getsignal(sig)
    calls = []
    async def immediate_work(providers):
        # No await: reproduces rejected/invalid records and providers that return
        # immediately. Bound the fixture so a regression cannot hang pytest.
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            signal.getsignal(sig)(sig, None)
        return len(calls) < 5
    monkeypatch.setattr(worker, 'process_one', immediate_work)
    asyncio.run(worker.run())
    assert calls == [1]
    assert signal.getsignal(sig) == previous


def test_busy_stop_leaves_next_database_attempt_unstarted(delivery_case, monkeypatch):
    sessions, first_id, recipient_id, event_id = delivery_case
    with sessions() as session:
        set_active(session, recipient_id, False)
        second = Alert(event_id=event_id, recipient_id=recipient_id, channel='EMAIL', status='PENDING')
        session.add(second)
        session.flush()
        second_id = second.id
    provider = AsyncMock()
    monkeypatch.setattr(worker, 'session_scope', sessions)
    monkeypatch.setattr(worker, 'configured_providers', lambda: {'EMAIL': provider})
    monkeypatch.setenv('ALERT_POLL_INTERVAL_SECONDS', '0.01')
    async def process_and_request_stop(providers):
        result = await process_one(providers, sessions)
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        return result
    monkeypatch.setattr(worker, 'process_one', process_and_request_stop)
    asyncio.run(worker.run())
    provider.send.assert_not_awaited()
    with sessions() as session:
        assert session.get(Alert, first_id).status == 'FAILED'
        remaining = session.get(Alert, second_id)
        assert remaining.status == 'PENDING' and remaining.attempt_started_at is None


def test_worker_startup_error_is_sanitized(monkeypatch, caplog):
    monkeypatch.setattr('sys.argv', ['worker', '--once'])
    monkeypatch.setattr(worker, 'run', AsyncMock(side_effect=RuntimeError('fake_secret')))
    assert worker.main() == 1
    assert 'operational_failure' in caplog.text and 'fake_secret' not in caplog.text


def test_cli_add_list_and_deactivate_without_sending(db, monkeypatch, capsys):
    @contextmanager
    def sessions():
        with db.begin_nested():
            yield db
    monkeypatch.setattr(admin, 'session_scope', sessions)
    monkeypatch.setattr('sys.argv', ['admin', 'add-recipient', '--name', 'Fixture',
                                    '--channel', 'EMAIL', '--destination', 'fixture@example.invalid'])
    assert admin.main() == 0
    recipient = db.scalar(select(AlertRecipient))
    monkeypatch.setattr('sys.argv', ['admin', 'deactivate-recipient', str(recipient.id)])
    assert admin.main() == 0 and not recipient.is_active
    monkeypatch.setattr('sys.argv', ['admin', 'list-recipients', '--limit', '10'])
    assert admin.main() == 0
    assert 'fixture@example.invalid' not in capsys.readouterr().out

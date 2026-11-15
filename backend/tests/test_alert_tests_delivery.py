"""Test queue across committed transactions, with simulated transports only."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import logging
from queue import Queue
import signal
from threading import Barrier, Event as ThreadEvent
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from app.alerts import admin as cli, worker
from app.alerts.base import ProviderError
from app.alerts.email import EmailProvider
from app.alerts.providers import providers_for_tests
from app.models import Alert, AlertRecipient, AlertTestAttempt, Event, User
from app.repositories import alert_tests as repository
from app.schemas.alert_admin import RecipientUpdate
from app.services import alert_tests
from app.services.alert_admin import AlertAdminError, add_recipient, update_recipient
from app.services.alert_test_delivery import process_one
from app.services.alert_delivery import process_one as process_real
from app.services import events
from app.schemas.events import EventRequest
from test_alert_admin_api import configured
from test_alert_providers import email_settings
from test_event_concurrency import concurrent_database
from test_operational_concurrency import wait_for_database_lock


@pytest.fixture
def queue_case(concurrent_database, configured):
    sessions, _, (_, users) = concurrent_database
    with sessions() as session:
        for identifier in users:
            session.get(User, identifier).role = 'ADMIN'
        recipient = add_recipient(session, 'Test', 'EMAIL', 'test@example.invalid')
        row, _ = alert_tests.create(session, recipient.id, users[0], uuid4())
        ids = row.id, recipient.id, users
    return sessions, *ids


def attempt(case):
    sessions, identifier, *_ = case
    with sessions() as session:
        return alert_tests.get(session, identifier)


def test_committed_reservation_fixed_body_and_no_real_history(queue_case, caplog):
    sessions, identifier, *_ = queue_case
    calls = []
    class Provider:
        async def send(self, message, destination):
            with sessions() as session:
                row = session.scalar(select(AlertTestAttempt).where(AlertTestAttempt.id == identifier)
                                     .with_for_update(nowait=True))
                assert row.status == 'PENDING' and row.attempt_started_at >= row.created_at
                assert str(row.uuid) in message and destination == row.destination
            assert 'teste' in message and 'não representa uma falha' in message
            calls.append(message)
    with caplog.at_level(logging.INFO):
        assert asyncio.run(process_one({'EMAIL': Provider()}, sessions))
    row = attempt(queue_case)
    assert row.status == 'SENT' and row.sent_at >= row.attempt_started_at
    assert not asyncio.run(process_one({'EMAIL': Provider()}, sessions))
    assert len(calls) == 1 and 'test@example.invalid' not in caplog.text
    with sessions() as session:
        for model in (Event, Alert):
            assert session.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize('error,code', [
    (ProviderError('email_app_password_required'), 'email_app_password_required'),
    (ProviderError('email_auth_rejected'), 'email_auth_rejected'),
    (ProviderError('email_auth_connection_failed'), 'email_auth_connection_failed'),
    (ProviderError('telegram_rejected'), 'telegram_rejected'),
    (ProviderError('email_rejected'), 'email_rejected'),
    (ProviderError('private-secret'), 'delivery_unconfirmed'),
    (OSError('private-secret'), 'delivery_unconfirmed'),
])
def test_failed_transport_is_safe_without_retry(queue_case, error, code, caplog):
    sessions, *_ = queue_case
    provider = AsyncMock()
    provider.send.side_effect = error
    assert asyncio.run(process_one({'EMAIL': provider}, sessions))
    row = attempt(queue_case)
    assert row.status == 'FAILED' and row.error_message == code and row.sent_at is None
    assert not asyncio.run(process_one({'EMAIL': provider}, sessions))
    provider.send.assert_awaited_once()
    assert 'private-secret' not in caplog.text


@pytest.mark.parametrize('failure_at', [1, 2])
def test_commit_failure_never_duplicates_delivery(queue_case, failure_at):
    sessions, *_ = queue_case
    count = 0
    @contextmanager
    def failing():
        nonlocal count
        count += 1
        with sessions() as session:
            yield session
            if count == failure_at:
                raise RuntimeError('commit_failure')
    provider = AsyncMock()
    with pytest.raises(RuntimeError, match='commit_failure'):
        asyncio.run(process_one({'EMAIL': provider}, failing))
    row = attempt(queue_case)
    assert row.status == 'PENDING' and (row.attempt_started_at is None) == (failure_at == 1)
    assert provider.send.await_count == failure_at - 1
    assert asyncio.run(process_one({'EMAIL': provider}, sessions)) == (failure_at == 1)
    assert provider.send.await_count == 1


def test_cancel_and_reconcile_never_resend(queue_case, monkeypatch, capsys):
    sessions, identifier, recipient_id, users = queue_case
    provider = AsyncMock()
    provider.send.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(process_one({'EMAIL': provider}, sessions))
    original = attempt(queue_case)
    assert original.status == 'PENDING' and original.attempt_started_at is not None
    assert not asyncio.run(process_one({'EMAIL': provider}, sessions))
    with pytest.raises(AlertAdminError, match='test_pending'):
        with sessions() as session:
            alert_tests.create(session, recipient_id, users[0], uuid4())
    monkeypatch.setattr(cli, 'session_scope', sessions)
    monkeypatch.setattr('sys.argv', ['admin', 'reconcile-test', str(identifier)])
    assert cli.main() == 1
    assert attempt(queue_case) == original
    monkeypatch.setattr('sys.argv', ['admin', 'reconcile-test', str(identifier), '--workers-stopped'])
    assert cli.main() == 0
    row = attempt(queue_case)
    assert row.status == 'FAILED' and row.error_message == 'delivery_unconfirmed'
    assert row.attempt_started_at == original.attempt_started_at
    assert cli.main() == 1
    with pytest.raises(alert_tests.CooldownActive):
        with sessions() as session:
            alert_tests.create(session, recipient_id, users[0], uuid4())
    monkeypatch.setenv('ALERT_TEST_COOLDOWN_SECONDS', '0')
    with sessions() as session:
        new, created = alert_tests.create(session, recipient_id, users[0], uuid4())
        assert created and new.id != identifier
    provider.send.assert_awaited_once()
    assert 'test@example.invalid' not in capsys.readouterr().out


def test_reconcile_unstarted_refused(queue_case):
    sessions, identifier, *_ = queue_case
    with pytest.raises(AlertAdminError, match='test_not_uncertain'):
        with sessions() as session:
            alert_tests.reconcile(session, identifier, workers_stopped=True)


@pytest.mark.parametrize('change,code', [('user_inactive', 'requester_inactive'),
    ('role', 'requester_not_admin'), ('recipient_inactive', 'recipient_inactive'),
    ('destination', 'recipient_identity_changed'), ('channel', 'recipient_identity_changed')])
def test_revalidate_before_transport(queue_case, change, code):
    sessions, _, recipient_id, users = queue_case
    with sessions() as session:
        if change == 'user_inactive':
            session.get(User, users[0]).is_active = False
        elif change == 'role':
            session.get(User, users[0]).role = 'VIEWER'
        else:
            target = session.get(AlertRecipient, recipient_id)
            if change == 'recipient_inactive':
                target.is_active = False
            elif change == 'destination':
                target.destination = 'changed@example.invalid'
            else:
                target.channel = 'TELEGRAM'
    provider = AsyncMock()
    assert asyncio.run(process_one({'EMAIL': provider}, sessions))
    row = attempt(queue_case)
    assert row.status == 'FAILED' and row.error_message == code
    provider.send.assert_not_awaited()


def test_disabled_channel_and_skip_locked(queue_case):
    sessions, identifier, *_ = queue_case
    provider = AsyncMock()
    assert not asyncio.run(process_one({}, sessions))
    assert attempt(queue_case).attempt_started_at is None
    with sessions() as session:
        session.scalar(select(AlertTestAttempt).where(AlertTestAttempt.id == identifier).with_for_update())
        assert not asyncio.run(process_one({'EMAIL': provider}, sessions))
    provider.send.assert_not_awaited()
    assert asyncio.run(process_one({'EMAIL': provider}, sessions))


def test_two_workers_reserve_once(queue_case):
    sessions, *_ = queue_case
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


@pytest.mark.parametrize('scenario', ['identical', 'different_uuid', 'different_recipient', 'different_user'])
def test_concurrent_creation(concurrent_database, configured, scenario):
    sessions, _, (_, users) = concurrent_database
    with sessions() as session:
        for identifier in users:
            session.get(User, identifier).role = 'ADMIN'
        recipients = [add_recipient(session, 'Test', 'EMAIL', f'{i}@example.invalid').id for i in range(2)]
    identifier = uuid4()
    barrier = Barrier(2, timeout=10)
    def submit(index):
        try:
            with sessions() as session:
                barrier.wait()
                row, created = alert_tests.create(session,
                    recipients[index] if scenario == 'different_recipient' else recipients[0],
                    users[index] if scenario == 'different_user' else users[0],
                    uuid4() if scenario == 'different_uuid' else identifier)
                return row.id, created
        except AlertAdminError:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit, i) for i in range(2)]
        results = [f.result(timeout=20) for f in futures]
    if scenario == 'identical':
        assert results[0][0] == results[1][0] and {r[1] for r in results} == {True, False}
    else:
        assert results.count('conflict') == 1
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(AlertTestAttempt)) == 1


@pytest.mark.parametrize('first', ['edit', 'enqueue'])
def test_edit_enqueue_serialization(concurrent_database, configured, first):
    sessions, _, (_, users) = concurrent_database
    with sessions() as session:
        session.get(User, users[0]).role = 'ADMIN'
        recipient_id = add_recipient(session, 'Test', 'EMAIL', 'old@example.invalid').id
    pids = Queue()
    def competing():
        try:
            with sessions() as session:
                pids.put(session.scalar(text('SELECT pg_backend_pid()')))
                if first == 'edit':
                    row, _ = alert_tests.create(session, recipient_id, users[0], uuid4())
                    return row.destination
                update_recipient(session, recipient_id, RecipientUpdate(destination='new@example.invalid'))
        except AlertAdminError:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=1) as pool:
        with sessions() as session:
            if first == 'edit':
                update_recipient(session, recipient_id, RecipientUpdate(destination='new@example.invalid'))
            else:
                alert_tests.create(session, recipient_id, users[0], uuid4())
            future = pool.submit(competing)
            wait_for_database_lock(sessions, pids.get(timeout=5))
        result = future.result(timeout=20)
    assert result == ('new@example.invalid' if first == 'edit' else 'conflict')


@pytest.mark.parametrize('parent', ['user', 'recipient'])
def test_reservation_reloads_cached_eligibility_after_lock(queue_case, parent):
    sessions, identifier, recipient_id, users = queue_case
    locked, release = ThreadEvent(), ThreadEvent()
    pids = Queue()
    model, key = (User, users[0]) if parent == 'user' else (AlertRecipient, recipient_id)
    def deactivate():
        with sessions() as session:
            session.get(model, key).is_active = False
            session.flush()
            locked.set()
            assert release.wait(10)
    def reserve():
        with sessions() as session:
            cached = session.get(model, key)
            assert cached.is_active
            pids.put(session.scalar(text('SELECT pg_backend_pid()')))
            return repository.reserve(session, ('EMAIL',))
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(deactivate)
        try:
            assert locked.wait(5)
            second = pool.submit(reserve)
            wait_for_database_lock(sessions, pids.get(timeout=5))
        finally:
            release.set()
        first.result(timeout=10)
        assert second.result(timeout=10) == (True, None)
    assert attempt(queue_case).error_message == ('requester_inactive' if parent == 'user' else 'recipient_inactive')


def test_creation_rechecks_user_after_lock(concurrent_database, configured):
    sessions, _, (_, users) = concurrent_database
    with sessions() as session:
        session.get(User, users[0]).role = 'ADMIN'
        recipient_id = add_recipient(session, 'Test', 'EMAIL', 'test@example.invalid').id
    pids = Queue()
    def create():
        with sessions() as session:
            cached = session.get(User, users[0])
            assert cached.role == 'ADMIN'
            pids.put(session.scalar(text('SELECT pg_backend_pid()')))
            alert_tests.create(session, recipient_id, users[0], uuid4())
    with ThreadPoolExecutor(max_workers=1) as pool:
        with sessions() as session:
            session.get(User, users[0]).role = 'VIEWER'
            session.flush()
            future = pool.submit(create)
            wait_for_database_lock(sessions, pids.get(timeout=5))
        with pytest.raises(alert_tests.RequesterDenied):
            future.result(timeout=10)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(AlertTestAttempt)) == 0


def test_deactivation_after_reservation_does_not_cancel_send(queue_case):
    sessions, _, recipient_id, users = queue_case
    provider = AsyncMock()
    async def send(message, destination):
        with sessions() as session:
            session.get(AlertRecipient, recipient_id).is_active = False
            session.get(User, users[0]).is_active = False
        assert destination == 'test@example.invalid'
    provider.send.side_effect = send
    assert asyncio.run(process_one({'EMAIL': provider}, sessions))
    assert attempt(queue_case).status == 'SENT'


@pytest.mark.parametrize('empty', [None, 'real', 'test'])
def test_worker_fairness_and_empty_queue_progress(queue_case, monkeypatch, empty):
    sessions, *_ = queue_case
    monkeypatch.setattr(worker, 'session_scope', sessions)
    monkeypatch.setattr(worker, 'configured_providers', lambda: {})
    handled = []
    def processor(name):
        async def process(providers):
            if name == empty:
                return False
            handled.append(name)
            if len(handled) == 6:
                signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            return True
        return process
    monkeypatch.setattr(worker, 'process_one', processor('real'))
    monkeypatch.setattr(worker, 'process_test', processor('test'))
    asyncio.run(worker.run())
    assert handled == (['real', 'test'] * 3 if empty is None else ['test' if empty == 'real' else 'real'] * 6)


def test_worker_once_processes_only_one_item(queue_case, monkeypatch):
    sessions, *_ = queue_case
    monkeypatch.setattr(worker, 'session_scope', sessions)
    monkeypatch.setattr(worker, 'configured_providers', lambda: {})
    real = AsyncMock(return_value=True)
    test = AsyncMock(return_value=True)
    monkeypatch.setattr(worker, 'process_one', real)
    monkeypatch.setattr(worker, 'process_test', test)
    asyncio.run(worker.run(once=True))
    real.assert_awaited_once()
    test.assert_not_awaited()


def test_fixed_test_subject_keeps_real_subject_and_provider_protocol(monkeypatch):
    connection = MagicMock()
    connection.ehlo.return_value = (250, b'ok')
    connection.send_message.return_value = {}
    monkeypatch.setattr('app.alerts.email._SMTP', lambda *a, **k: connection)
    original = EmailProvider(email_settings())
    telegram = AsyncMock()
    real = {'EMAIL': original, 'TELEGRAM': telegram}
    test = providers_for_tests(real)
    assert test['TELEGRAM'] is telegram and real['EMAIL'] is original
    asyncio.run(test['EMAIL'].send('Test', 'test@example.invalid'))
    assert connection.send_message.call_args.args[0]['Subject'] == 'Machine Monitor — teste de envio'
    asyncio.run(original.send('Fault', 'test@example.invalid'))
    assert connection.send_message.call_args.args[0]['Subject'] == 'Machine Monitor — alerta'


def test_worker_consumes_both_persisted_queues_fairly(concurrent_database, configured, monkeypatch):
    sessions, payload, (_, users) = concurrent_database
    with sessions() as session:
        session.get(User, users[0]).role = 'ADMIN'
        for index in range(3):
            target = add_recipient(session, 'Test', 'EMAIL', f'{index}@example.invalid')
            alert_tests.create(session, target.id, users[0], uuid4())
        events.create(session, EventRequest(**payload))
        assert session.scalar(select(func.count()).select_from(Alert)) == 3
    calls = []
    class Provider:
        async def send(self, message, destination):
            calls.append('test' if 'Identificador do teste:' in message else 'real')
            if len(calls) == 6:
                signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
    monkeypatch.setattr(worker, 'configured_providers', lambda: {'EMAIL': Provider()})
    monkeypatch.setattr(worker, 'session_scope', sessions)
    async def real(providers):
        return await process_real(providers, sessions)
    async def test(providers):
        return await process_one(providers, sessions)
    monkeypatch.setattr(worker, 'process_one', real)
    monkeypatch.setattr(worker, 'process_test', test)
    asyncio.run(worker.run())
    assert calls == ['real', 'test'] * 3
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Event)) == 1
        for model in (Alert, AlertTestAttempt):
            assert session.scalar(select(func.count()).select_from(model).where(model.status == 'SENT')) == 3

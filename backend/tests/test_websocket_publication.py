"""Real PostgreSQL commits and bounded fan-out without external messages."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.api import dependencies
from app.main import app
from app.models import Alert, AlertRecipient, Event
from app.websocket.connection import ProtocolViolation
from app.websocket.manager import ConnectionManager
from app.websocket.schemas import EventNotification
from test_event_concurrency import concurrent_database

KEY = 'publication-test-key'


@pytest.fixture
def publication_api(concurrent_database, monkeypatch):
    sessions, payload, _ = concurrent_database
    received = []

    class Publisher:
        def publish(self, notification):
            # A different DB connection must already see the committed row.
            with sessions() as session:
                assert session.get(Event, notification.event_id) is not None
            received.append(notification)

    publisher = Publisher()
    monkeypatch.setenv('DEVICE_API_KEY', KEY)
    monkeypatch.setattr(dependencies, 'session_scope', sessions)
    monkeypatch.setattr(app.state, 'event_connections', publisher, raising=False)
    with TestClient(app) as client:
        yield client, payload | {'uuid': str(payload['uuid'])}, received, sessions, publisher


def post(client, payload):
    return client.post('/api/v1/events', json=payload, headers={'X-API-Key': KEY})


@pytest.mark.parametrize('kind', ['FAULT_CONFIRMED', 'FAULT_RECOVERED', 'DEVICE_OFFLINE',
                                 'DEVICE_ONLINE', 'COLOR_RED', 'ALARM_SOUND'])
def test_committed_types_and_replay(publication_api, kind):
    client, payload, received, _, _ = publication_api
    payload['event_type'] = kind
    created = post(client, payload)
    assert created.status_code == 201
    assert post(client, payload).status_code == 200
    assert post(client, payload | {'message': 'conflict'}).status_code == 409
    assert len(received) == (0 if kind in {'COLOR_RED', 'ALARM_SOUND'} else 1)
    if received:
        assert received[0].model_dump(mode='json') == {
            'type': kind, 'event_id': created.json()['id'], 'uuid': payload['uuid'],
            'machine_id': payload['machine_id'], 'timestamp': '2026-10-22T12:00:00Z',
            'severity': 'CRITICAL'}


def test_outer_commit_not_savepoint(publication_api, monkeypatch):
    client, payload, received, sessions, _ = publication_api

    @contextmanager
    def checked_sessions():
        with sessions() as session:
            yield session
            # Ingestion has released its savepoint, but root is not committed.
            assert session.scalar(select(Event.id)) is not None
            assert received == []
        assert received == []  # Publication belongs to the dependency after this.

    monkeypatch.setattr(dependencies, 'session_scope', checked_sessions)
    assert post(client, payload).status_code == 201
    assert len(received) == 1


def test_root_failure_never_publishes(publication_api, monkeypatch):
    client, payload, received, sessions, _ = publication_api

    @contextmanager
    def failed_commit():
        with sessions() as session:
            yield session
            raise SQLAlchemyError('test-only persistence failure')

    monkeypatch.setattr(dependencies, 'session_scope', failed_commit)
    assert post(client, payload).status_code == 503
    assert received == []
    with sessions() as session:
        assert session.scalar(select(Event.id)) is None


def test_postcommit_publication_failure_preserves_success(publication_api, monkeypatch, caplog):
    client, payload, received, sessions, publisher = publication_api

    def fail(notification):
        raise RuntimeError('sensitive detail must not be logged')

    monkeypatch.setattr(publisher, 'publish', fail)
    assert post(client, payload).status_code == 201
    assert post(client, payload).status_code == 200
    with sessions() as session:
        assert len(list(session.scalars(select(Event)))) == 1
    assert received == []
    assert 'websocket_publication_failed' in caplog.text
    assert 'sensitive detail' not in caplog.text


def test_concurrent_replay_only_one_publication(publication_api):
    client, payload, received, _, _ = publication_api
    barrier = Barrier(2, timeout=5)

    def submit():
        barrier.wait()
        return post(client, payload).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit) for _ in range(2)]
        assert sorted(f.result(timeout=15) for f in futures) == [200, 201]
    assert len(received) == 1


def notification():
    return EventNotification(type='DEVICE_ONLINE', event_id=1, uuid=uuid4(), machine_id=1,
                             timestamp='2026-11-12T12:00:00Z', severity='INFO')


def test_slow_subscriber_isolated_and_tasks_cleaned():
    async def scenario():
        manager = ConnectionManager()
        blocked = asyncio.Event()
        fast_received = asyncio.Queue()

        class Slow:
            async def wait_for_disconnect(self):
                await asyncio.Future()

            async def send(self, message):
                blocked.set()
                await asyncio.Future()

        class Fast(Slow):
            async def send(self, message):
                fast_received.put_nowait(message)

        slow = asyncio.create_task(manager.serve(Slow(), 1))
        fast = asyncio.create_task(manager.serve(Fast(), 1))
        await asyncio.sleep(0)
        first = notification()
        manager.publish(first)
        await asyncio.wait_for(blocked.wait(), 1)
        assert await asyncio.wait_for(fast_received.get(), 1) == first
        second = notification()
        manager.publish(second)
        assert await asyncio.wait_for(fast_received.get(), 1) == second
        third = notification()
        manager.publish(third)
        assert await asyncio.wait_for(fast_received.get(), 1) == third
        with pytest.raises(ProtocolViolation) as caught:
            await asyncio.wait_for(slow, 1)
        assert caught.value.code == 1013
        assert len(manager.subscribers) == 1
        fast.cancel()
        await asyncio.gather(fast, return_exceptions=True)
        assert not manager.subscribers
        assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]

    asyncio.run(scenario())


@pytest.mark.parametrize('error', [TimeoutError(), RuntimeError('transport failed')])
def test_sender_failure_removes_client(error):
    async def scenario():
        manager = ConnectionManager()
        connection = AsyncMock()

        async def pending():
            await asyncio.Future()

        connection.wait_for_disconnect.side_effect = pending
        connection.send.side_effect = error
        task = asyncio.create_task(manager.serve(connection, 1))
        await asyncio.sleep(0)
        manager.publish(notification())
        with pytest.raises(type(error)):
            await asyncio.wait_for(task, 1)
        assert not manager.subscribers

    asyncio.run(scenario())


def test_closed_loop_publication_is_safe(caplog):
    async def create_manager():
        return ConnectionManager()

    manager = asyncio.run(create_manager())
    manager.publish(notification())
    assert 'websocket_publication_unavailable' in caplog.text


@pytest.mark.parametrize('failure', ['publication', 'transaction'])
def test_alert_queue_remains_atomic_and_idempotent(publication_api, monkeypatch, failure):
    client, payload, received, sessions, publisher = publication_api
    # Only enable enqueueing in this isolated schema; no worker/provider is run.
    monkeypatch.setenv('EMAIL_ENABLED', 'true')
    monkeypatch.setenv('ALERT_COOLDOWN_SECONDS', '60')
    with sessions() as session:
        session.add(AlertRecipient(name='Isolated WS test', channel='EMAIL',
                                   destination='ws-test@example.invalid', is_active=True))

    if failure == 'publication':
        def fail(notification):
            raise RuntimeError('isolated publication failure')
        monkeypatch.setattr(publisher, 'publish', fail)
        assert post(client, payload).status_code == 201
        assert post(client, payload).status_code == 200
    else:
        @contextmanager
        def failed_transaction():
            with sessions() as session:
                yield session
                assert len(list(session.scalars(select(Alert)))) == 1
                raise SQLAlchemyError('isolated transaction failure')
        monkeypatch.setattr(dependencies, 'session_scope', failed_transaction)
        assert post(client, payload).status_code == 503

    assert received == []
    with sessions() as session:
        events = list(session.scalars(select(Event)))
        alerts = list(session.scalars(select(Alert)))
        if failure == 'transaction':
            assert events == [] and alerts == []
        else:
            assert len(events) == len(alerts) == 1
            assert alerts[0].event_id == events[0].id
            assert alerts[0].status == 'PENDING'
            assert alerts[0].attempt_started_at is None

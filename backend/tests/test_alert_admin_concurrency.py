"""Recipient editing races against enqueue/reservation/retry, on real transactions."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event as Signal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select, text

from app.models import Alert, AlertRecipient
from app.repositories import alert_delivery
from app.schemas.alert_admin import RecipientUpdate
from app.schemas.events import EventRequest
from app.services import alert_admin, events
from app.services.alert_delivery import process_one
from test_event_concurrency import concurrent_database
from test_operational_concurrency import wait_for_database_lock
from test_alert_delivery import delivery_case


@pytest.mark.parametrize('change,queued', [
    ({'is_active': False}, False),
    ({'channel': 'TELEGRAM', 'destination': '12345'}, False),
    ({'destination': 'new@example.invalid'}, True),
])
def test_edit_commit_precedes_enqueue_and_refreshes_cached_recipient(concurrent_database, monkeypatch, change, queued):
    sessions, values, _ = concurrent_database
    monkeypatch.setenv('EMAIL_ENABLED', 'true')
    monkeypatch.setenv('ALERT_COOLDOWN_SECONDS', '0')
    with sessions() as session:
        identifier = alert_admin.add_recipient(session, 'Test', 'EMAIL', 'old@example.invalid').id
    locked, release = Signal(), Signal()
    pids = Queue()
    def edit():
        with sessions() as session:
            alert_admin.update_recipient(session, identifier, RecipientUpdate(**change))
            locked.set()
            assert release.wait(10)
    def enqueue():
        with sessions() as session:
            cached = session.get(AlertRecipient, identifier)
            assert cached.destination == 'old@example.invalid'
            pids.put(session.scalar(text('SELECT pg_backend_pid()')))
            events.create(session, EventRequest(**values))
            return session.scalar(select(func.count()).select_from(Alert))
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(edit)
        try:
            assert locked.wait(5)
            second = pool.submit(enqueue)
            wait_for_database_lock(sessions, pids.get(timeout=5))
        finally:
            release.set()
        first.result(timeout=10)
        assert second.result(timeout=10) == int(queued)
    with sessions() as session:
        if queued:
            found, delivery = alert_delivery.reserve(session, ('EMAIL',))
            assert found and delivery.destination == 'new@example.invalid'
        else:
            assert session.scalar(select(func.count()).select_from(Alert)) == 0


def test_enqueue_commit_freezes_identity_before_waiting_editor(concurrent_database, monkeypatch):
    sessions, values, _ = concurrent_database
    monkeypatch.setenv('EMAIL_ENABLED', 'true')
    monkeypatch.setenv('ALERT_COOLDOWN_SECONDS', '0')
    with sessions() as session:
        identifier = alert_admin.add_recipient(session, 'Test', 'EMAIL', 'old@example.invalid').id
    locked, release = Signal(), Signal()
    pids = Queue()
    def enqueue():
        with sessions() as session:
            events.create(session, EventRequest(**values))
            locked.set()
            assert release.wait(10)
    def edit():
        with sessions() as session:
            pids.put(session.scalar(text('SELECT pg_backend_pid()')))
            alert_admin.update_recipient(session, identifier, RecipientUpdate(destination='new@example.invalid'))
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(enqueue)
        try:
            assert locked.wait(5)
            second = pool.submit(edit)
            wait_for_database_lock(sessions, pids.get(timeout=5))
        finally:
            release.set()
        first.result(timeout=10)
        with pytest.raises(alert_admin.AlertAdminConflict, match='recipient_identity_has_attempts'):
            second.result(timeout=10)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Alert)) == 1
        assert session.get(AlertRecipient, identifier).destination == 'old@example.invalid'


@pytest.mark.parametrize('action', ['reserve', 'retry'])
def test_deactivation_rechecked_after_wait_for_recipient_lock(delivery_case, action):
    sessions, identifier, recipient_id, _ = delivery_case
    if action == 'retry':
        with sessions() as session:
            row = session.get(Alert, identifier)
            row.status, row.error_message = 'FAILED', 'delivery_unconfirmed'
    locked, release = Signal(), Signal()
    pids = Queue()
    def deactivate():
        with sessions() as session:
            alert_admin.set_active(session, recipient_id, False)
            locked.set()
            assert release.wait(10)
    def act():
        with sessions() as session:
            cached = session.get(AlertRecipient, recipient_id)
            assert cached.is_active
            pids.put(session.scalar(text('SELECT pg_backend_pid()')))
            if action == 'reserve':
                return alert_delivery.reserve(session, ('EMAIL',))
            alert_admin.retry(session, identifier, accept_duplicate_risk=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(deactivate)
        try:
            assert locked.wait(5)
            second = pool.submit(act)
            wait_for_database_lock(sessions, pids.get(timeout=5))
        finally:
            release.set()
        first.result(timeout=10)
        if action == 'reserve':
            assert second.result(timeout=10) == (True, None)
        else:
            with pytest.raises(alert_admin.AlertAdminError, match='attempt_not_eligible'):
                second.result(timeout=10)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Alert)) == 1
        if action == 'reserve':
            row = session.get(Alert, identifier)
            assert row.status == 'FAILED' and row.error_message == 'recipient_inactive'


def test_deactivation_after_committed_reservation_does_not_cancel_delivery(delivery_case):
    sessions, identifier, recipient_id, _ = delivery_case
    async def simulate_send(message, destination):
        with sessions() as session:
            assert session.get(Alert, identifier).attempt_started_at is not None
            alert_admin.set_active(session, recipient_id, False)
        assert destination == 'fixture@example.invalid'
    provider = AsyncMock()
    provider.send.side_effect = simulate_send
    assert asyncio.run(process_one({'EMAIL': provider}, sessions))
    provider.send.assert_awaited_once()
    with sessions() as session:
        assert session.get(Alert, identifier).status == 'SENT'
        assert session.get(AlertRecipient, recipient_id).is_active is False

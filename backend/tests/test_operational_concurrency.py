"""Real transactions prove context boundaries survive concurrent ingestion."""

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event as Signal
import time

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.models import Device, Machine
from app.schemas.equipment import DeviceUpdate
from app.schemas.events import EventRequest
from app.services import equipment, events, operational
from app.services.equipment import Conflict
from test_event_concurrency import concurrent_database
from test_domain import status_migration


def wait_for_database_lock(sessions, pid):
    deadline = time.monotonic() + 5  # Test-only deadline.
    while time.monotonic() < deadline:
        with sessions() as session:
            if session.scalar(text('SELECT cardinality(pg_blocking_pids(:pid))'), {'pid': pid}):
                return
        time.sleep(0.01)
    pytest.fail('Concurrent writer did not reach the expected PostgreSQL lock')


@pytest.mark.parametrize('action', ['reassociate', 'reactivate'])
def test_event_commit_precedes_context_change(concurrent_database, action):
    sessions, values, _ = concurrent_database
    values = values | {'event_type': 'DEVICE_ONLINE'}
    with sessions() as session:
        other = Machine(serial_number='other', name='Other', block='T', corridor='T', status='NORMAL')
        session.add(other)
        session.flush()
        other_id = other.id
    written, release = Signal(), Signal()
    pids = Queue()

    def ingest():
        with sessions() as session:
            row, _ = events.create(session, EventRequest(**values))
            if action == 'reactivate':
                equipment.update_device(session, values['device_id'], DeviceUpdate(is_active=False))
            written.set()
            assert release.wait(10)
            return row.id

    def change():
        with sessions() as session:
            # Keep the pre-commit identity cached to prove the lock refreshes it.
            old = session.get(Device, values['device_id'])
            assert old.is_active is True
            pids.put(session.scalar(text('SELECT pg_backend_pid()')))
            payload = DeviceUpdate(machine_id=other_id) if action == 'reassociate' else DeviceUpdate(is_active=True)
            return equipment.update_device(session, old.id, payload).status_event_id_floor

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(ingest)
        try:
            assert written.wait(5)
            second = pool.submit(change)
            wait_for_database_lock(sessions, pids.get(timeout=5))
        finally:
            release.set()
        assert second.result(timeout=10) == first.result(timeout=10)
    with sessions() as session:
        target = other_id if action == 'reassociate' else values['machine_id']
        assert operational.list_states(session, target)[0].availability == 'UNKNOWN'


@pytest.mark.parametrize('target_is_new_machine', [False, True])
def test_context_change_precedes_ingestion(concurrent_database, target_is_new_machine):
    sessions, values, _ = concurrent_database
    with sessions() as session:
        other = Machine(serial_number='other', name='Other', block='T', corridor='T', status='NORMAL')
        session.add(other)
        session.flush()
        other_id = other.id
    changed, release = Signal(), Signal()
    pids = Queue()

    def change():
        with sessions() as session:
            equipment.update_device(session, values['device_id'], DeviceUpdate(machine_id=other_id))
            changed.set()
            assert release.wait(10)

    def ingest():
        with sessions() as session:
            pids.put(session.scalar(text('SELECT pg_backend_pid()')))
            payload = values | {'event_type': 'DEVICE_ONLINE',
                                'machine_id': other_id if target_is_new_machine else values['machine_id']}
            try:
                return events.create(session, EventRequest(**payload))[1]
            except Conflict:
                return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(change)
        try:
            assert changed.wait(5)
            second = pool.submit(ingest)
            wait_for_database_lock(sessions, pids.get(timeout=5))
        finally:
            release.set()
        first.result(timeout=10)
        assert second.result(timeout=10) is target_is_new_machine
    with sessions() as session:
        result = operational.list_states(session, other_id)[0]
        assert result.availability == ('ONLINE' if target_is_new_machine else 'UNKNOWN')


def test_migration_backfill_blocks_ingestion_until_commit(concurrent_database):
    sessions, values, _ = concurrent_database
    with sessions() as session:
        old_id = events.create(session, EventRequest(**(values | {'event_type': 'DEVICE_ONLINE'})))[0].id
        with Operations.context(MigrationContext.configure(session.connection())):
            status_migration().downgrade()
    migrated, release = Signal(), Signal()
    pids = Queue()

    def migrate():
        with sessions() as session:
            with Operations.context(MigrationContext.configure(session.connection())):
                status_migration().upgrade()
            migrated.set()
            assert release.wait(10)

    def ingest():
        from uuid import uuid4
        with sessions() as session:
            pids.put(session.scalar(text('SELECT pg_backend_pid()')))
            return events.create(session, EventRequest(**(values | {
                'uuid': uuid4(), 'event_type': 'DEVICE_ONLINE'})))[0].id

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(migrate)
        try:
            assert migrated.wait(5)
            second = pool.submit(ingest)
            wait_for_database_lock(sessions, pids.get(timeout=5))
        finally:
            release.set()
        first.result(timeout=10)
        new_id = second.result(timeout=10)
    with sessions() as session:
        assert session.get(Device, values['device_id']).status_event_id_floor == old_id
        result = operational.list_states(session, values['machine_id'])[0]
        assert result.availability == 'ONLINE'
        assert result.device_evidence[0].connection_event.event_id == new_id > old_id

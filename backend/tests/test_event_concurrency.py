"""Independent PostgreSQL transactions in a private, explicitly cleaned schema."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.database.session import database_url
from app.models import Device, Event, Machine, User
from app.repositories import events as repository
from app.schemas.domain import EventRead
from app.schemas.events import EventRequest
from app.services import events
from app.services.equipment import Conflict
from test_domain import domain_migration


@pytest.fixture
def concurrent_database():
    if not os.environ.get('DATABASE_URL'):
        pytest.skip('Requires PostgreSQL')
    engine = create_engine(database_url(), hide_parameters=True)
    schema = 'test_events_' + uuid4().hex
    # Only a generated private schema is committed; never touch public tables.
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        with Operations.context(MigrationContext.configure(connection)):
            domain_migration().upgrade()

    @contextmanager
    def session_scope():
        with Session(engine, expire_on_commit=False) as session:
            with session.begin():
                session.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                # Test-only failure bounds, not application operational settings.
                session.execute(text("SET LOCAL statement_timeout = '10s'"))
                yield session

    try:
        with session_scope() as session:
            machine = Machine(serial_number='fixture', name='Fixture', block='Test', corridor='Test', status='NORMAL')
            devices = [Device(machine=machine, device_uid=f'fixture-{i}', device_name='Fixture') for i in range(2)]
            users = [User(name='Fixture', email=f'fixture-{i}@example.invalid', password_hash='fixture', role='OPERATOR') for i in range(2)]
            session.add_all([*devices, *users])
            session.flush()
            payload = dict(uuid=uuid4(), machine_id=machine.id, device_id=devices[0].id,
                           event_type='FAULT_CONFIRMED', severity='CRITICAL',
                           started_at='2026-10-22T12:00:00Z', message='Concurrent fixture')
            ids = ([device.id for device in devices], [user.id for user in users])
        yield session_scope, payload, ids
    finally:
        try:
            with engine.begin() as connection:
                connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                with Operations.context(MigrationContext.configure(connection)):
                    domain_migration().downgrade()
                connection.execute(text(f'DROP SCHEMA "{schema}"'))
        finally:
            engine.dispose()


def test_concurrent_identical_uuid(concurrent_database):
    session_scope, values, _ = concurrent_database
    barrier = Barrier(2, timeout=10)

    def submit():
        with session_scope() as session:
            barrier.wait()
            row, created = events.create(session, EventRequest(**values))
            return row.id, created

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit) for _ in range(2)]
        results = [future.result(timeout=20) for future in futures]
    assert results[0][0] == results[1][0]
    assert sorted(created for _, created in results) == [False, True]
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(Event)) == 1


def test_concurrent_uuid_conflict_different_devices(concurrent_database, monkeypatch):
    session_scope, values, (device_ids, _) = concurrent_database
    barrier = Barrier(2, timeout=10)
    original = events.get_machine

    def synchronized_machine(session, identifier, **kwargs):
        # Both UUID lookups finish before contending for the new machine lock.
        # A barrier inside insert would deadlock after serialization was added.
        barrier.wait()
        return original(session, identifier, **kwargs)

    monkeypatch.setattr(events, 'get_machine', synchronized_machine)

    def submit(device_id):
        with session_scope() as session:
            try:
                row, created = events.create(session, EventRequest(**(values | {'device_id': device_id})))
                assert created
                return row.device_id
            except Conflict:
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit, id) for id in device_ids]
        results = [future.result(timeout=20) for future in futures]
    assert results.count(None) == 1
    with session_scope() as session:
        rows = list(session.scalars(select(Event)))
        assert len(rows) == 1 and rows[0].device_id in results


def test_concurrent_acknowledgment_preserves_winner(concurrent_database):
    session_scope, values, (_, user_ids) = concurrent_database
    with session_scope() as session:
        event, _ = events.create(session, EventRequest(**values))
        identifier = event.id
    barrier = Barrier(2, timeout=10)

    def acknowledge(user_id):
        with session_scope() as session:
            # Exercise a stale identity-map value as well as row-lock contention.
            events.get(session, identifier)
            barrier.wait()
            return EventRead.model_validate(events.acknowledge(session, identifier, user_id))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(acknowledge, id) for id in user_ids]
        results = [future.result(timeout=20) for future in futures]
    assert results[0] == results[1]
    assert results[0].acknowledged_by in user_ids
    with session_scope() as session:
        assert EventRead.model_validate(events.get(session, identifier)) == results[0]

"""Dashboard contracts against PostgreSQL in rollback-isolated schemas."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from itertools import product
from uuid import uuid4

import pytest
import jwt
from fastapi.testclient import TestClient
from sqlalchemy import event as sql_event, func, literal, select
from sqlalchemy.exc import OperationalError

from app.api import dependencies
from app.main import app
from app.models import Alert, Device, Event, Machine
from app.repositories import dashboard as repository
from app.schemas.dashboard import MachineStatusFilters, PeriodFilters
from app.security import issue_token
from app.services import dashboard, operational
from test_auth import settings, user
from test_domain import db
from test_equipment import client, admin, KEY
from test_operational import fleet, emit
from test_event_concurrency import concurrent_database

BASE = '/api/v1/dashboard'
PERIOD = {'start_date': '2026-11-14T00:00:00Z', 'end_date': '2026-11-15T00:00:00Z', 'bucket': 'day'}
ROUTES = [('summary', {}), ('machine-status', {}), ('events-by-period', PERIOD)]


def get(client, admin, route, **params):
    response = client.get(BASE + '/' + route, headers=admin, params=params)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize('role', ['ADMIN', 'OPERATOR', 'VIEWER'])
@pytest.mark.parametrize('route,params', ROUTES)
def test_roles_and_empty_responses(client, admin, db, user, role, route, params):
    # Token was issued before the persisted role was changed.
    user.role = role
    db.flush()
    result = get(client, admin, route, **params)
    assert result['as_of'].endswith('Z')
    if route == 'summary':
        assert all(value == 0 for key, value in result.items() if key != 'as_of')
    elif route == 'machine-status':
        assert result['total'] == 0 and result['items'] == []
        assert result['limit'] == 50 and result['offset'] == 0
    else:
        assert result['items'] == [{'start': PERIOD['start_date'], 'end': PERIOD['end_date'], 'count': 0}]


@pytest.mark.parametrize('route,params', ROUTES)
@pytest.mark.parametrize('credential', ['missing', 'device', 'refresh', 'inactive', 'expired'])
def test_access_token_and_active_user_required(client, admin, db, user, settings, route, params, credential):
    headers = {}
    if credential == 'device':
        headers = {'X-API-Key': KEY}
    elif credential == 'refresh':
        headers = {'Authorization': 'Bearer ' + issue_token(user.id, 'refresh', settings)}
    elif credential == 'inactive':
        headers = admin
        user.is_active = False
        db.flush()
    elif credential == 'expired':
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        headers = {'Authorization': 'Bearer ' + jwt.encode(
            {'sub': str(user.id), 'iat': yesterday, 'exp': yesterday + timedelta(minutes=1),
             'token_type': 'access'}, settings.secret, algorithm=settings.algorithm)}
    assert client.get(BASE + '/' + route, headers=headers, params=params).status_code == 401


def test_all_state_combinations_match_summary_and_filtered_pages(client, admin, db):
    expected = {key: [] for key in ('NORMAL', 'FAULT', 'OFFLINE', 'MAINTENANCE', 'UNKNOWN')}
    # Exhaustive parity of SQL aggregation/filtering and the stage-2 read model.
    for index, (registered, fault, connection) in enumerate(product(
            ('NORMAL', 'FAULT', 'OFFLINE', 'MAINTENANCE'),
            (None, 'FAULT_CONFIRMED', 'FAULT_RECOVERED'),
            (None, 'DEVICE_ONLINE', 'DEVICE_OFFLINE'))):
        machine = Machine(serial_number=f'dashboard-{index}', name='Test', block='T', corridor='T', status=registered)
        device = Device(machine=machine, device_uid=f'dashboard-{index}', device_name='Test')
        db.add_all([machine, device])
        db.flush()
        for kind in (fault, connection):
            if kind:
                emit(db, machine, device, kind)
    states = operational.list_states(db)
    for machine in states:
        expected[machine.operational_status or 'UNKNOWN'].append(machine.machine_id)
    summary = get(client, admin, 'summary')
    assert summary['total_machines'] == 36 == sum(summary[key.lower()] for key in expected)
    for status, identifiers in expected.items():
        assert summary[status.lower()] == len(identifiers)
        page = get(client, admin, 'machine-status', status=status, limit=200)
        assert page['total'] == len(identifiers)
        assert [item['machine_id'] for item in page['items']] == identifiers
        assert all((item['operational_status'] or 'UNKNOWN') == status for item in page['items'])
    page = get(client, admin, 'machine-status', limit=2, offset=1)
    assert page['total'] == 36
    assert page['items'] == [state.model_dump(mode='json') for state in states[1:3]]
    assert get(client, admin, 'machine-status', offset=36)['items'] == []
    assert get(client, admin, 'machine-status', offset=36)['total'] == 36
    for params in ({'machine_id': 9223372036854775807}, {'machine_id': states[0].machine_id, 'status': 'FAULT'}):
        empty = get(client, admin, 'machine-status', **params)
        assert empty['total'] == 0 and empty['items'] == []
    assert db.scalar(select(func.count()).select_from(Alert)) == 0


def test_multiple_devices_count_machines_once_and_filter_before_pagination(client, admin, db, fleet):
    machines, devices = fleet
    emit(db, machines[0], devices[0], 'DEVICE_OFFLINE')
    # OFFLINE + UNKNOWN is UNKNOWN. Zero devices is also UNKNOWN.
    result = get(client, admin, 'summary')
    assert result['total_machines'] == result['unknown'] == 2
    emit(db, machines[0], devices[1], 'DEVICE_OFFLINE')
    result = get(client, admin, 'machine-status', status='OFFLINE', limit=1)
    assert result['total'] == 1 and len(result['items']) == 1
    assert len(result['items'][0]['device_evidence']) == 2
    assert get(client, admin, 'summary')['offline'] == 1
    devices[1].is_active = False
    db.flush()
    assert len(get(client, admin, 'machine-status', machine_id=machines[0].id)['items'][0]['device_evidence']) == 1


def test_critical_window_is_half_open_includes_acknowledged_any_type(client, admin, db, fleet, user, monkeypatch):
    machines, devices = fleet
    clock = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
    class FixedQueryClock:
        def statement_timestamp(self):
            return literal(clock)

        def __getattr__(self, name):
            return getattr(func, name)
    monkeypatch.setattr(repository, 'func', FixedQueryClock())
    for delta, severity, kind in [
        (-timedelta(days=1, microseconds=1), 'CRITICAL', 'COLOR_RED'),
        (-timedelta(days=1), 'CRITICAL', 'COLOR_RED'),
        (-timedelta(microseconds=1), 'CRITICAL', 'ALARM_SOUND'),
        (timedelta(0), 'CRITICAL', 'COLOR_RED'),
        (timedelta(days=1), 'CRITICAL', 'COLOR_RED'),
        (-timedelta(hours=1), 'WARNING', 'FAULT_CONFIRMED'),
    ]:
        event, _ = emit(db, machines[0], devices[0], kind, severity=severity, started_at=clock + delta)
        event.acknowledged = True
        event.acknowledged_by = user.id
        event.acknowledged_at = clock
        db.flush()
    result = get(client, admin, 'summary')
    assert result['as_of'] == '2026-11-14T12:00:00Z'
    assert result['critical_events_24h'] == 2


def test_hourly_utc_clipped_boundaries_and_filters(client, admin, db, fleet, user):
    machines, devices = fleet
    for at, kind, severity in [
        ('2026-11-14T00:29:59.999999Z', 'COLOR_RED', 'INFO'),
        ('2026-11-14T00:30:00Z', 'COLOR_RED', 'INFO'),
        ('2026-11-14T01:00:00Z', 'COLOR_RED', 'CRITICAL'),
        ('2026-11-14T01:00:00Z', 'ALARM_SOUND', 'INFO'),
        ('2026-11-14T02:59:59.999999Z', 'COLOR_RED', 'INFO'),
        ('2026-11-14T03:15:00Z', 'COLOR_RED', 'INFO'),
    ]:
        row, _ = emit(db, machines[0], devices[0], kind, severity=severity, started_at=at)
        row.acknowledged = True
        row.acknowledged_by = user.id
        row.acknowledged_at = datetime.now(timezone.utc)
        db.flush()
    params = dict(start_date='2026-11-13T20:30:00-04:00', end_date='2026-11-13T23:15:00-04:00', bucket='hour')
    result = get(client, admin, 'events-by-period', **params)
    assert result['start_date'] == '2026-11-14T00:30:00Z'
    assert result['end_date'] == '2026-11-14T03:15:00Z'
    assert [item['count'] for item in result['items']] == [1, 2, 1, 0]
    assert result['items'][0]['start'] == result['start_date']
    assert result['items'][-1]['end'] == result['end_date']
    assert all(left['end'] == right['start'] for left, right in zip(result['items'], result['items'][1:]))
    filtered = get(client, admin, 'events-by-period', **params, machine_id=machines[0].id,
                   event_type='COLOR_RED', severity='CRITICAL')
    assert [item['count'] for item in filtered['items']] == [0, 1, 0, 0]
    for identifier in (machines[1].id, 9223372036854775807):
        assert all(item['count'] == 0 for item in get(client, admin, 'events-by-period',
                   **params, machine_id=identifier)['items'])


def test_daily_utc_clipping_future_and_200_bucket_boundary(client, admin, db, fleet):
    machines, devices = fleet
    emit(db, machines[0], devices[0], 'COLOR_RED', started_at='2099-03-02T00:00:00Z')
    params = dict(start_date='2099-03-01T12:30:00Z', end_date='2099-03-03T00:30:00Z', bucket='day')
    result = get(client, admin, 'events-by-period', **params)
    assert [item['count'] for item in result['items']] == [0, 1, 0]
    assert result['items'][0]['end'] == '2099-03-02T00:00:00Z'
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for bucket, step in [('hour', timedelta(hours=200)), ('day', timedelta(days=200))]:
        params = dict(start_date=start.isoformat(), end_date=(start + step).isoformat(), bucket=bucket)
        assert len(get(client, admin, 'events-by-period', **params)['items']) == 200
        params['end_date'] = (start + step + timedelta(microseconds=1)).isoformat()
        assert client.get(BASE + '/events-by-period', headers=admin, params=params).status_code == 422
    # datetime upper limit must not overflow when finding the next day/hour.
    for bucket in ('hour', 'day'):
        result = get(client, admin, 'events-by-period', start_date='9999-12-31T23:30:00Z',
                     end_date='9999-12-31T23:59:59.999999Z', bucket=bucket)
        assert len(result['items']) == 1 and result['items'][0]['count'] == 0


@pytest.mark.parametrize('change', [
    {'start_date': None}, {'end_date': None}, {'bucket': None}, {'bucket': 'week'},
    {'start_date': '2026-11-14T00:00:00'}, {'end_date': '2026-11-13T00:00:00Z'},
    {'end_date': PERIOD['start_date']}, {'machine_id': 0}, {'machine_id': 9223372036854775808},
    {'event_type': 'bogus'}, {'severity': 'bogus'}, {'extra': 'forbidden'},
    {'start_date': '0001-01-01T00:00:00+01:00'}, {'start_date': '0001-01-01T00:00:00Z'},
])
def test_invalid_period_inputs(client, admin, change):
    params = {key: value for key, value in (PERIOD | change).items() if value is not None}
    assert client.get(BASE + '/events-by-period', headers=admin, params=params).status_code == 422


@pytest.mark.parametrize('params', [
    {'limit': 0}, {'limit': 201}, {'offset': -1}, {'offset': 9223372036854775808},
    {'machine_id': 0}, {'machine_id': 9223372036854775808}, {'status': 'ONLINE'}, {'extra': 'forbidden'},
])
def test_invalid_status_inputs(client, admin, params):
    assert client.get(BASE + '/machine-status', headers=admin, params=params).status_code == 422


def test_each_dashboard_response_uses_one_read_statement(db, fleet):
    statements = []
    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    connection = db.connection()
    sql_event.listen(connection, 'before_cursor_execute', record)
    try:
        for query in (lambda: dashboard.summary(db),
                      lambda: dashboard.machine_status(db, MachineStatusFilters(limit=1)),
                      lambda: dashboard.events_by_period(db, PeriodFilters(**PERIOD))):
            statements.clear()
            query()
            assert len(statements) == 1
            assert statements[0].lstrip().upper().startswith(('SELECT', 'WITH'))
    finally:
        sql_event.remove(connection, 'before_cursor_execute', record)


@pytest.mark.parametrize('route', ['summary', 'machine-status', 'events-by-period'])
def test_concurrent_commit_does_not_mix_response_snapshots(concurrent_database, route):
    sessions, values, _ = concurrent_database
    when = datetime.now(timezone.utc) - timedelta(seconds=1)
    period = PeriodFilters(start_date=when - timedelta(minutes=1),
                           end_date=when + timedelta(minutes=1), bucket='hour')
    queries = {
        'summary': dashboard.summary,
        'machine-status': lambda session: dashboard.machine_status(session, MachineStatusFilters()),
        'events-by-period': lambda session: dashboard.events_by_period(session, period),
    }
    def commit_between_query_and_serialization(conn, cursor, statement, parameters, context, executemany):
        # The reader has executed its SELECT; a separate transaction commits
        # before result assembly. Metadata/items must still reflect that SELECT.
        with sessions() as writer:
            writer.add(Machine(serial_number='added-concurrently', name='Test', block='T',
                               corridor='T', status='MAINTENANCE'))
            writer.add(Event(**(values | {'uuid': uuid4(), 'started_at': when})))
            writer.flush()
    with sessions() as reader:
        connection = reader.connection()
        sql_event.listen(connection, 'after_cursor_execute', commit_between_query_and_serialization, once=True)
        try:
            before = queries[route](reader)
        finally:
            sql_event.remove(connection, 'after_cursor_execute', commit_between_query_and_serialization)
        after = queries[route](reader)
    if route == 'summary':
        assert before.total_machines == before.unknown == 1
        assert before.fault == before.critical_events_24h == 0
        assert after.total_machines == 2 and after.fault == after.maintenance == after.critical_events_24h == 1
    elif route == 'machine-status':
        assert before.total == len(before.items) == 1 and before.items[0].fault_active is None
        assert after.total == len(after.items) == 2 and after.items[0].fault_active is True
    else:
        assert sum(item.count for item in before.items) == 0
        assert sum(item.count for item in after.items) == 1


@pytest.mark.parametrize('route,params', ROUTES)
@pytest.mark.parametrize('failure', ['connect', 'query'])
def test_database_failure_is_503_never_empty_success(db, admin, monkeypatch, route, params, failure):
    @contextmanager
    def scope():
        if failure == 'connect':
            raise OperationalError('SELECT', {}, Exception('private-database-detail'))
        yield db
    def fail(*args, **kwargs):
        raise OperationalError('SELECT', {}, Exception('private-database-detail'))
    monkeypatch.setattr(dependencies, 'session_scope', scope)
    if failure == 'query':
        monkeypatch.setattr(repository, route.replace('-', '_'), fail)
    # Use the actual get_session exception boundary, not the test client override.
    with TestClient(app) as instance:
        response = instance.get(BASE + '/' + route, headers=admin, params=params)
    assert response.status_code == 503
    assert response.json() == {'detail': 'Database unavailable'}
    assert 'private-database-detail' not in response.text

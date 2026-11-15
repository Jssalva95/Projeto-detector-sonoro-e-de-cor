"""Real admin routes, isolated persistence, no live providers or deliveries."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import logging

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event as sql_event, func, select
from sqlalchemy.exc import OperationalError

from app.api import dependencies
from app.main import app
from app.models import Alert, AlertRecipient, Event
from app.schemas.alert_admin import AlertFilters, RecipientFilters
from app.security import issue_token
from app.services import alert_admin, alert_queries
from test_auth import settings, user
from test_domain import db, records
from test_equipment import client, admin, KEY

RECIPIENTS = '/api/v1/alert-recipients'
ALERTS = '/api/v1/alerts'
SETTINGS = '/api/v1/settings'
PAYLOAD = {'name': 'Fixture', 'channel': 'EMAIL', 'destination': 'fixture@example.invalid'}
ROUTES = [('get', RECIPIENTS), ('get', RECIPIENTS + '/1'), ('post', RECIPIENTS),
          ('patch', RECIPIENTS + '/1'), ('get', ALERTS), ('get', ALERTS + '/1'), ('get', SETTINGS)]


@pytest.mark.parametrize('method,path', ROUTES)
@pytest.mark.parametrize('identity', ['missing', 'device', 'refresh', 'inactive', 'expired', 'OPERATOR', 'VIEWER'])
def test_admin_only_for_every_route(client, admin, db, user, settings, method, path, identity):
    headers = admin
    expected = 401
    if identity == 'missing':
        headers = {}
    elif identity == 'device':
        headers = {'X-API-Key': KEY}
    elif identity == 'refresh':
        headers = {'Authorization': 'Bearer ' + issue_token(user.id, 'refresh', settings)}
    elif identity == 'inactive':
        user.is_active = False
        db.flush()
    elif identity == 'expired':
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        headers = {'Authorization': 'Bearer ' + jwt.encode(
            {'sub': str(user.id), 'iat': yesterday, 'exp': yesterday + timedelta(minutes=1), 'token_type': 'access'},
            settings.secret, algorithm=settings.algorithm)}
    else:
        user.role = identity  # Existing token must obey the current database role.
        db.flush()
        expected = 403
    response = client.request(method, path, headers=headers,
                              **({'json': PAYLOAD} if method in ('post', 'patch') else {}))
    assert response.status_code == expected
    assert PAYLOAD['destination'] not in response.text
    assert db.scalar(select(func.count()).select_from(AlertRecipient)) == 0


def test_recipient_crud_duplicates_partial_updates_and_cli(client, admin, db, caplog):
    for path in (RECIPIENTS, ALERTS):
        assert client.get(path, headers=admin).json() == {'total': 0, 'limit': 50, 'offset': 0, 'items': []}
    with caplog.at_level(logging.INFO):
        first = client.post(RECIPIENTS, headers=admin, json=PAYLOAD)
        assert first.status_code == 201
        assert first.headers['cache-control'] == 'no-store'
        row = first.json()
        assert row['is_active'] is True and row['created_at'].endswith('Z')
        duplicate = client.post(RECIPIENTS, headers=admin, json=PAYLOAD | {'is_active': False})
        assert duplicate.status_code == 201 and duplicate.json()['id'] != row['id']
        path = RECIPIENTS + '/' + str(row['id'])
        assert client.get(path, headers=admin).json() == row
        changed = client.patch(path, headers=admin, json={'channel': 'TELEGRAM', 'destination': '-12345'})
        assert changed.status_code == 200 and changed.json()['channel'] == 'TELEGRAM'
        assert client.patch(path, headers=admin, json={}).json() == changed.json()
        alert_admin.set_active(db, row['id'], False)
        assert client.get(path, headers=admin).json()['is_active'] is False
        assert client.patch(path, headers=admin, json={'is_active': True}).json()['is_active'] is True
        assert client.delete(path, headers=admin).status_code == 405
    assert PAYLOAD['destination'] not in caplog.text
    assert db.scalar(select(func.count()).select_from(Alert)) == 0
    assert db.scalar(select(func.count()).select_from(Event)) == 0


@pytest.mark.parametrize('change', [
    {'name': ''}, {'name': ' \t'}, {'name': 'x\ny'}, {'name': 'x\x00y'},
    {'destination': 'secret\r\nBcc: hidden@example.invalid'}, {'destination': 'a..b@example.invalid'},
    {'channel': 'SMS'}, {'channel': 'WHATSAPP'}, {'channel': 'TELEGRAM', 'destination': '123/path'},
    {'password': 'secret-input'}, {'name': None}, {'destination': None}, {'is_active': None},
])
def test_invalid_creation_never_echoes_or_inserts(client, admin, db, change):
    result = client.post(RECIPIENTS, headers=admin, json=PAYLOAD | change)
    assert result.status_code == 422
    assert 'secret' not in result.text and 'hidden@example.invalid' not in result.text
    assert db.scalar(select(func.count()).select_from(AlertRecipient)) == 0


@pytest.mark.parametrize('field', ['name', 'channel', 'destination', 'is_active'])
def test_patch_rejects_null_without_mutation(client, admin, field):
    row = client.post(RECIPIENTS, headers=admin, json=PAYLOAD).json()
    path = RECIPIENTS + '/' + str(row['id'])
    assert client.patch(path, headers=admin, json={field: None}).status_code == 422
    assert client.get(path, headers=admin).json() == row


@pytest.mark.parametrize('status', ['PENDING', 'FAILED', 'SENT'])
def test_any_existing_attempt_freezes_identity_but_allows_name_and_activity(client, admin, db, records, status):
    recipient, attempt = records[-2:]
    attempt.status = status
    db.flush()
    path = RECIPIENTS + '/' + str(recipient.id)
    original = client.get(path, headers=admin).json()
    for change in ({'destination': 'other@example.invalid'}, {'channel': 'TELEGRAM', 'destination': '123'}):
        assert client.patch(path, headers=admin, json=change).status_code == 409
        assert client.get(path, headers=admin).json() == original
    assert client.patch(path, headers=admin, json={'destination': original['destination']}).status_code == 200
    changed = client.patch(path, headers=admin, json={'name': 'Renamed', 'is_active': False})
    assert changed.status_code == 200 and changed.json()['name'] == 'Renamed'
    alert_admin.set_active(db, recipient.id, True)
    assert client.get(path, headers=admin).json()['is_active'] is True


@pytest.mark.parametrize('channel', ['SMS', 'WHATSAPP'])
def test_legacy_channels_list_deactivate_but_not_activate(client, admin, db, channel):
    row = AlertRecipient(name='Legacy', channel=channel, destination='legacy-value', is_active=True)
    db.add(row)
    db.flush()
    path = RECIPIENTS + '/' + str(row.id)
    assert client.get(RECIPIENTS, headers=admin, params={'channel': channel}).json()['total'] == 1
    assert client.patch(path, headers=admin, json={'is_active': False}).status_code == 200
    assert client.patch(path, headers=admin, json={'is_active': True}).status_code == 422
    with pytest.raises(alert_admin.AlertAdminError):
        alert_admin.set_active(db, row.id, True)
    assert client.get(path, headers=admin).json()['is_active'] is False


def test_filters_order_and_total_survive_empty_pages(client, admin, db, records):
    recipient = records[-2]
    other = alert_admin.add_recipient(db, 'Other', 'TELEGRAM', '@fixture')
    alert_admin.add_recipient(db, 'Inactive', 'EMAIL', 'inactive@example.invalid', is_active=False)
    result = client.get(RECIPIENTS, headers=admin, params={'channel': 'EMAIL', 'is_active': True}).json()
    assert result['total'] == 1 and result['items'][0]['id'] == recipient.id
    page = client.get(RECIPIENTS, headers=admin, params={'offset': 1, 'limit': 1}).json()
    assert page['total'] == 3 and page['items'][0]['id'] == other.id
    assert client.get(RECIPIENTS, headers=admin, params={'offset': 100}).json() == {
        'total': 3, 'limit': 50, 'offset': 100, 'items': []}
    event = records[4]
    newer = Alert(event_id=event.id, recipient_id=other.id, channel='TELEGRAM', status='FAILED', error_message='private-secret')
    db.add(newer)
    db.flush()
    page = client.get(ALERTS, headers=admin, params={'limit': 1}).json()
    assert page['total'] == 2 and page['items'][0]['id'] == newer.id
    assert page['items'][0]['error_message'] == 'delivery_unconfirmed'
    detail = client.get(ALERTS + '/' + str(newer.id), headers=admin)
    assert detail.json() == page['items'][0] and 'private-secret' not in detail.text
    assert db.get(Alert, newer.id).error_message == 'private-secret'  # no rewrite of history
    params = {'machine_id': event.machine_id, 'event_id': event.id, 'recipient_id': other.id,
              'channel': 'TELEGRAM', 'status': 'FAILED'}
    assert client.get(ALERTS, headers=admin, params=params).json()['total'] == 1
    params['machine_id'] = 9223372036854775807
    assert client.get(ALERTS, headers=admin, params=params).json()['total'] == 0
    assert client.get(ALERTS, headers=admin, params={'offset': 100}).json()['total'] == 2
    assert client.get(ALERTS, headers=admin, params={'offset': 100}).json()['items'] == []


def test_all_safe_failure_codes_and_no_error(db, records):
    attempt = records[-1]
    for code in (*alert_queries.PUBLIC_ERRORS, None):
        attempt.error_message = code
        assert alert_queries.public_alert(attempt).error_message == code


@pytest.mark.parametrize('path', [RECIPIENTS, ALERTS])
@pytest.mark.parametrize('params', [{'limit': 201}, {'limit': 0}, {'offset': -1},
    {'offset': 9223372036854775808}, {'channel': 'BOGUS'}, {'extra': 'secret'}])
def test_invalid_filters(client, admin, path, params):
    response = client.get(path, headers=admin, params=params)
    assert response.status_code == 422 and 'secret' not in response.text


@pytest.mark.parametrize('path', [RECIPIENTS, ALERTS])
def test_missing_and_invalid_ids(client, admin, path):
    assert client.get(path + '/9223372036854775807', headers=admin).status_code == 404
    assert client.get(path + '/0', headers=admin).status_code == 422
    assert client.get(path + '/9223372036854775808', headers=admin).status_code == 422
    if path == RECIPIENTS:
        assert client.patch(path + '/9223372036854775807', headers=admin, json={}).status_code == 404


@pytest.fixture
def configured(monkeypatch):
    for key, value in {'EMAIL_ENABLED': 'true', 'SMTP_HOST': 'smtp.example.invalid', 'SMTP_PORT': '587',
                       'SMTP_TLS_MODE': 'starttls', 'SMTP_TIMEOUT_SECONDS': '2',
                       'SMTP_FROM': 'sender@example.invalid', 'SMTP_USER': 'private-user', 'SMTP_PASSWORD': 'private-secret',
                       'ALERT_COOLDOWN_SECONDS': '300', 'ALERT_POLL_INTERVAL_SECONDS': '10',
                       'ALERT_TEST_COOLDOWN_SECONDS': '300'}.items():
        monkeypatch.setenv(key, value)


def test_settings_allowlist_and_disabled_nulls(client, admin, monkeypatch):
    monkeypatch.setenv('SMTP_PASSWORD', 'private-secret')
    monkeypatch.setenv('ALERT_TEST_COOLDOWN_SECONDS', 'invalid-disabled')
    response = client.get(SETTINGS, headers=admin)
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert response.json() == {'email_enabled': False, 'telegram_enabled': False,
                              'alert_cooldown_seconds': None, 'alert_poll_interval_seconds': None,
                              'alert_test_cooldown_seconds': None}


def test_enabled_settings_only_safe_values(client, admin, configured, monkeypatch, caplog):
    monkeypatch.setenv('TELEGRAM_ENABLED', 'true')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', '123:private_token')
    monkeypatch.setenv('TELEGRAM_TIMEOUT_SECONDS', '2')
    with caplog.at_level(logging.INFO):
        response = client.get(SETTINGS, headers=admin)
    assert response.status_code == 200
    assert response.json() == {'email_enabled': True, 'telegram_enabled': True,
                              'alert_cooldown_seconds': 300, 'alert_poll_interval_seconds': 10,
                              'alert_test_cooldown_seconds': 300}
    assert 'private' not in response.text + caplog.text


@pytest.mark.parametrize('key,value', [('EMAIL_ENABLED', 'invalid'), ('SMTP_HOST', ''),
    ('ALERT_TEST_COOLDOWN_SECONDS', ''), ('ALERT_TEST_COOLDOWN_SECONDS', 'nan'),
    ('ALERT_TEST_COOLDOWN_SECONDS', '-1'), ('ALERT_TEST_COOLDOWN_SECONDS', 'inf'),
    ('ALERT_COOLDOWN_SECONDS', ''), ('ALERT_POLL_INTERVAL_SECONDS', '0'), ('SMTP_PORT', 'private-secret')])
def test_bad_active_configuration_is_sanitized_503(client, admin, configured, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    response = client.get(SETTINGS, headers=admin)
    assert response.status_code == 503
    assert response.json() == {'detail': 'Alert configuration unavailable'}


def test_zero_test_cooldown_is_explicit_not_default(client, admin, configured, monkeypatch):
    monkeypatch.setenv('ALERT_TEST_COOLDOWN_SECONDS', '0')
    assert client.get(SETTINGS, headers=admin).json()['alert_test_cooldown_seconds'] == 0


def test_pages_are_one_statement_each(db, records):
    statements = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    connection = db.connection()
    sql_event.listen(connection, 'before_cursor_execute', capture)
    try:
        alert_queries.recipients(db, RecipientFilters())
        alert_queries.alerts(db, AlertFilters())
    finally:
        sql_event.remove(connection, 'before_cursor_execute', capture)
    assert len(statements) == 2 and all(statement.lstrip().upper().startswith('WITH') for statement in statements)


@pytest.mark.parametrize('path', [RECIPIENTS, ALERTS, SETTINGS])
def test_database_unavailable_is_sanitized_503(admin, monkeypatch, path):
    @contextmanager
    def fail():
        raise OperationalError('SELECT', {}, Exception('private-secret'))
        yield
    monkeypatch.setattr(dependencies, 'session_scope', fail)
    with TestClient(app) as client:
        response = client.get(path, headers=admin)
    assert response.status_code == 503 and response.json() == {'detail': 'Database unavailable'}


@pytest.mark.parametrize('path,method', [(RECIPIENTS, 'recipients'), (ALERTS, 'alerts')])
def test_failed_query_is_not_empty_success(db, admin, monkeypatch, path, method):
    @contextmanager
    def scope():
        yield db
    def fail(*args, **kwargs):
        raise OperationalError('SELECT', {}, Exception('private-query-detail'))
    monkeypatch.setattr(dependencies, 'session_scope', scope)
    monkeypatch.setattr(alert_queries.repository, method, fail)
    with TestClient(app) as client:
        response = client.get(path, headers=admin)
    assert response.status_code == 503 and response.json() == {'detail': 'Database unavailable'}


def test_only_approved_admin_methods():
    paths = app.openapi()['paths']
    assert set(paths[RECIPIENTS]) == {'get', 'post'}
    assert set(paths[RECIPIENTS + '/{id}']) == {'get', 'patch'}
    for path in (ALERTS, ALERTS + '/{id}', SETTINGS):
        assert set(paths[path]) == {'get'}
    for _, path in ROUTES:
        path = path.replace('/1', '/{id}')
        for operation in paths[path].values():
            assert operation['security'] == [{'HTTPBearer': []}]
    for path, method in [('/api/v1/alert-tests', 'get'), ('/api/v1/alert-tests/{id}', 'get'),
                         (RECIPIENTS + '/{id}/test', 'post')]:
        assert set(paths[path]) == {method}
        assert paths[path][method]['security'] == [{'HTTPBearer': []}]

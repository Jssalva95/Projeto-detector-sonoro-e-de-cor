"""Approved test-send API and database invariants; isolated rows, no network."""

from datetime import timedelta
from contextlib import contextmanager
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, inspect, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import OperationalError
from fastapi.testclient import TestClient

from app.models import Alert, AlertRecipient, AlertTestAttempt, Event, User
from app.api import dependencies
from app.main import app
from app.repositories import alert_tests as repository
from app.security import issue_token
from app.services import alert_tests
from app.services.alert_admin import add_recipient
from test_alert_admin_api import configured
from test_auth import settings, user
from test_domain import db, records, delivery_test_migration
from test_equipment import client, admin

TESTS = '/api/v1/alert-tests'
RECIPIENTS = '/api/v1/alert-recipients'


@pytest.fixture
def target(db):
    return add_recipient(db, 'Test', 'EMAIL', 'test@example.invalid')


def submit(client, admin, target, identifier=None):
    return client.post(f'{RECIPIENTS}/{target.id}/test', headers=admin,
                       json={'uuid': str(identifier or uuid4())})


def complete(db, row, status='FAILED'):
    row.attempt_started_at = row.created_at
    row.status = status
    row.sent_at = row.created_at if status == 'SENT' else None
    row.error_message = None if status == 'SENT' else 'delivery_unconfirmed'
    db.flush()


def test_enqueue_replay_snapshot_and_private_output(client, admin, target, configured, db, user, caplog):
    identifier = uuid4()
    first = submit(client, admin, target, identifier)
    assert first.status_code == 202
    data = first.json()
    assert data['status'] == 'PENDING' and data['requested_by'] == user.id
    assert first.headers['cache-control'] == 'no-store'
    assert set(data) == {'id', 'uuid', 'recipient_id', 'requested_by', 'channel', 'status',
                         'created_at', 'attempt_started_at', 'sent_at', 'error_message'}
    row = db.get(AlertTestAttempt, data['id'])
    assert row.destination == target.destination and row.requester is user and row.recipient is target
    assert row in user.test_attempts and row in target.test_attempts
    assert submit(client, admin, target, identifier).status_code == 200
    assert client.get(f'{TESTS}/{row.id}', headers=admin).json() == data
    page = client.get(TESTS, headers=admin).json()
    assert page == {'total': 1, 'limit': 50, 'offset': 0, 'items': [data]}
    for model in (Event, Alert):
        assert db.scalar(select(func.count()).select_from(model)) == 0
    assert target.destination not in first.text + str(page) + caplog.text


def test_replay_precedes_eligibility_config_and_cooldown(client, admin, target, configured, db, monkeypatch):
    identifier = uuid4()
    result = submit(client, admin, target, identifier)
    row = db.get(AlertTestAttempt, result.json()['id'])
    complete(db, row)
    target.is_active = False
    db.flush()
    monkeypatch.setenv('EMAIL_ENABLED', 'false')
    monkeypatch.setenv('SMTP_PASSWORD', '')
    monkeypatch.delenv('ALERT_TEST_COOLDOWN_SECONDS')
    replay = submit(client, admin, target, identifier)
    assert replay.status_code == 200 and replay.json()['status'] == 'FAILED'
    assert replay.json()['id'] == row.id and row.created_at.isoformat()


def test_uuid_identity_conflict_and_identity_guard(client, admin, target, configured, db, user, settings):
    identifier = uuid4()
    first = submit(client, admin, target, identifier)
    other = add_recipient(db, 'Other', 'EMAIL', 'other@example.invalid')
    assert submit(client, admin, other, identifier).status_code == 409
    second_admin = User(name='Other', email='other@example.invalid', password_hash='test', role='ADMIN')
    db.add(second_admin)
    db.flush()
    headers = {'Authorization': 'Bearer ' + issue_token(second_admin.id, 'access', settings)}
    conflict = submit(client, headers, target, identifier)
    assert conflict.status_code == 409 and str(first.json()['uuid']) not in conflict.text
    path = f'{RECIPIENTS}/{target.id}'
    assert client.patch(path, headers=admin, json={'destination': 'new@example.invalid'}).status_code == 409
    assert client.patch(path, headers=admin, json={'channel': 'TELEGRAM', 'destination': '123'}).status_code == 409
    assert client.patch(path, headers=admin, json={'name': 'Renamed', 'is_active': False}).status_code == 200


@pytest.mark.parametrize('identity', ['missing', 'refresh', 'inactive', 'OPERATOR', 'VIEWER'])
@pytest.mark.parametrize('operation', ['create', 'list', 'get'])
def test_admin_access_enforced(client, admin, target, configured, db, user, settings, identity, operation):
    expected = 401
    headers = admin
    if identity == 'missing':
        headers = {}
    elif identity == 'refresh':
        headers = {'Authorization': 'Bearer ' + issue_token(user.id, 'refresh', settings)}
    elif identity == 'inactive':
        user.is_active = False
    else:
        user.role = identity
        expected = 403
    db.flush()
    result = (submit(client, headers, target) if operation == 'create' else
              client.get(TESTS + ('/1' if operation == 'get' else ''), headers=headers))
    assert result.status_code == expected
    assert db.scalar(select(func.count()).select_from(AlertTestAttempt)) == 0


@pytest.mark.parametrize('payload', [{}, {'uuid': 'bad'}, {'uuid': None},
    {'uuid': str(uuid4()), 'destination': 'private@example.invalid'},
    {'uuid': str(uuid4()), 'message': 'private'}, {'uuid': str(uuid4()), 'subject': 'private'}])
def test_no_arbitrary_payload(client, admin, target, configured, payload):
    response = client.post(f'{RECIPIENTS}/{target.id}/test', headers=admin, json=payload)
    assert response.status_code == 422 and 'private' not in response.text


@pytest.mark.parametrize('change,status', [('inactive', 409), ('disabled', 409), ('legacy', 409),
    ('destination', 409), ('config', 503), ('cooldown', 503)])
def test_ineligible_and_configuration(client, admin, target, configured, db, monkeypatch, change, status):
    if change == 'inactive':
        target.is_active = False
    elif change == 'legacy':
        target.channel = 'SMS'
    elif change == 'destination':
        target.destination = 'invalid'
    elif change == 'disabled':
        monkeypatch.setenv('EMAIL_ENABLED', 'false')
    elif change == 'config':
        monkeypatch.setenv('SMTP_PORT', 'private-secret')
    else:
        monkeypatch.delenv('ALERT_TEST_COOLDOWN_SECONDS')
    db.flush()
    response = submit(client, admin, target)
    assert response.status_code == status and 'private-secret' not in response.text
    assert db.scalar(select(func.count()).select_from(AlertTestAttempt)) == 0


@pytest.mark.parametrize('status', ['SENT', 'FAILED'])
def test_cooldown_boundary_and_independent_recipient(client, admin, target, configured, db, monkeypatch, status):
    first = submit(client, admin, target)
    row = db.get(AlertTestAttempt, first.json()['id'])
    complete(db, row, status)
    monkeypatch.setattr(alert_tests, 'database_now', lambda session: row.created_at + timedelta(seconds=299.1))
    response = submit(client, admin, target)
    assert response.status_code == 429 and response.headers['retry-after'] == '1'
    other = add_recipient(db, 'Other', 'EMAIL', 'other@example.invalid')
    assert submit(client, admin, other).status_code == 202
    monkeypatch.setattr(alert_tests, 'database_now', lambda session: row.created_at + timedelta(seconds=300))
    assert submit(client, admin, target).status_code == 202
    assert submit(client, admin, target).status_code == 409  # pending before cooldown


def test_uncertain_pending_blocks_new_request(client, admin, target, configured, db):
    row = db.get(AlertTestAttempt, submit(client, admin, target).json()['id'])
    row.attempt_started_at = row.created_at
    db.flush()
    assert submit(client, admin, target).json() == {'detail': 'test_pending'}


def test_filters_pages_and_sanitization(client, admin, target, configured, db, monkeypatch):
    monkeypatch.setenv('ALERT_TEST_COOLDOWN_SECONDS', '0')
    ids = []
    for status in ('SENT', 'FAILED', 'FAILED'):
        row = db.get(AlertTestAttempt, submit(client, admin, target).json()['id'])
        ids.append(row.id)
        complete(db, row, status)
    row.error_message = 'private-legacy-secret'
    db.flush()
    page = client.get(TESTS, headers=admin, params={'limit': 1, 'offset': 1, 'status': 'FAILED',
                                                 'recipient_id': target.id}).json()
    assert page['total'] == 2 and [r['id'] for r in page['items']] == [ids[1]]
    assert client.get(TESTS, headers=admin, params={'offset': 100}).json()['total'] == 3
    response = client.get(f'{TESTS}/{ids[-1]}', headers=admin)
    assert response.json()['error_message'] == 'delivery_unconfirmed'
    assert 'private' not in response.text
    assert row.error_message == 'private-legacy-secret'  # output-only sanitization
    assert client.get(f'{TESTS}/999999', headers=admin).status_code == 404
    assert client.post(f'{RECIPIENTS}/999999/test', headers=admin, json={'uuid': str(uuid4())}).status_code == 404
    for params in ({'limit': 201}, {'offset': -1}, {'status': 'INVALID'}, {'recipient_id': 0}):
        assert client.get(TESTS, headers=admin, params=params).status_code == 422


@pytest.mark.parametrize('values', [
    {'status': 'SENT'}, {'status': 'FAILED'}, {'status': 'INVALID'}, {'channel': 'SMS'},
    {'error_message': 'error'}, {'sent_at': 'creation'}, {'attempt_started_at': 'before'},
    {'status': 'SENT', 'attempt_started_at': 'creation', 'sent_at': 'before'},
    {'status': 'FAILED', 'attempt_started_at': 'creation', 'error_message': ''},
])
def test_database_constraints(db, user, target, configured, values):
    row, _ = alert_tests.create(db, target.id, user.id, uuid4())
    changes = {key: row.created_at if value == 'creation' else
               row.created_at - timedelta(seconds=1) if value == 'before' else value
               for key, value in values.items()}
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.execute(update(AlertTestAttempt).where(AlertTestAttempt.id == row.id).values(**changes))


def test_uniqueness_restrict_and_migration_preserves_real_history(db, records):
    _, user, _, _, _, recipient, real = records
    user.role = 'ADMIN'
    real.attempt_started_at = real.created_at
    db.flush()
    connection = db.connection()
    original = connection.execute(select(Alert.__table__)).mappings().all()
    with Operations.context(MigrationContext.configure(connection)):
        delivery_test_migration().downgrade()
        delivery_test_migration().upgrade()
    assert connection.execute(select(Alert.__table__)).mappings().all() == original
    inspector = inspect(connection)
    columns = {c['name']: c for c in inspector.get_columns('alert_test_attempts')}
    assert set(columns) == {'id', 'uuid', 'recipient_id', 'requested_by', 'channel', 'destination',
                            'status', 'created_at', 'attempt_started_at', 'sent_at', 'error_message'}
    assert columns['id']['identity'] and columns['created_at']['type'].timezone
    assert len(inspector.get_foreign_keys('alert_test_attempts')) == 2
    indexes = inspector.get_indexes('alert_test_attempts')
    assert any(i['unique'] and i['column_names'] == ['recipient_id'] and
               'PENDING' in str(i['dialect_options']) for i in indexes)
    row = AlertTestAttempt(uuid=uuid4(), recipient=recipient, requester=user, channel='EMAIL',
                           destination=recipient.destination, status='PENDING')
    db.add(row)
    db.flush()
    for same_uuid in (False, True):
        with pytest.raises(IntegrityError):
            with db.begin_nested():
                db.add(AlertTestAttempt(uuid=row.uuid if same_uuid else uuid4(), recipient=recipient,
                    requester=user, channel='EMAIL', destination=recipient.destination, status='PENDING'))
                db.flush()
    for parent in (user, recipient):
        assert parent.test_attempts
        with pytest.raises(IntegrityError):
            with db.begin_nested():
                db.delete(parent)
                db.flush()
        with pytest.raises(IntegrityError):
            with db.begin_nested():
                db.execute(update(type(parent)).where(type(parent).id == parent.id).values(id=999999))


def test_failed_request_commit_rolls_back_queue(db, user, admin, target, configured, monkeypatch):
    @contextmanager
    def fail_commit():
        with db.begin_nested():
            yield db
            raise OperationalError('COMMIT', {}, Exception('private-secret'))
    monkeypatch.setattr(dependencies, 'session_scope', fail_commit)
    with TestClient(app) as http:
        response = submit(http, admin, target)
    assert response.status_code == 503 and response.json() == {'detail': 'Database unavailable'}
    assert db.scalar(select(func.count()).select_from(AlertTestAttempt)) == 0


def test_uuid_unique_after_completed_attempt(db, user, target, configured):
    first, _ = alert_tests.create(db, target.id, user.id, uuid4())
    complete(db, first)
    other = add_recipient(db, 'Other', 'EMAIL', 'other@example.invalid')
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(AlertTestAttempt(uuid=first.uuid, recipient_id=other.id, requested_by=user.id,
                channel='EMAIL', destination=other.destination, status='PENDING'))
            db.flush()

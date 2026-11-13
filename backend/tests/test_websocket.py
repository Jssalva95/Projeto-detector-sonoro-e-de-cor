"""Phase 7.1 contracts and authentication; no publication or external delivery."""

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
import time
from unittest.mock import AsyncMock
from uuid import uuid4

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect
from uvicorn.logging import AccessFormatter

from app.api.websocket import router
from app.models import User
from app.security import InvalidCredentials, auth_settings, issue_token
from app.server import TransportLogFilter
from app.websocket import auth
from app.websocket.auth import ForbiddenUser, Principal
from app.websocket.config import WebSocketConfigurationError, WebSocketSettings, websocket_settings
from app.websocket.connection import AuthenticatedConnection
from app.websocket.schemas import AuthenticationMessage, AuthenticatedMessage, EventNotification
from test_domain import db

ORIGIN = 'http://localhost:5173'
PATH = '/api/v1/ws/events'


@pytest.fixture
def ws_environment(monkeypatch):
    for key, value in {
        'JWT_SECRET': 'isolated-websocket-key-' * 4, 'JWT_ALGORITHM': 'HS256',
        'JWT_ACCESS_TOKEN_EXPIRE_MINUTES': '5', 'JWT_REFRESH_TOKEN_EXPIRE_MINUTES': '30',
        'WS_AUTH_TIMEOUT_SECONDS': '0.1', 'WS_SEND_TIMEOUT_SECONDS': '1',
        'WS_MAX_MESSAGE_BYTES': '4096', 'WS_ALLOWED_ORIGINS': json.dumps([ORIGIN]),
        'WS_CLIENT_QUEUE_SIZE': '2',
    }.items():
        monkeypatch.setenv(key, value)
    return auth_settings()


@pytest.fixture
def account(db):
    user = User(name='WS fixture', email='ws@example.invalid', password_hash='unused-test-only',
                role='VIEWER', is_active=True)
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def client(db, monkeypatch, ws_environment):
    @contextmanager
    def sessions():
        db.expire_all()
        yield db
    monkeypatch.setattr(auth, 'session_scope', sessions)
    test_app = FastAPI()
    test_app.include_router(router)
    with TestClient(test_app) as instance:
        yield instance


def frame(token):
    return {'type': 'authenticate', 'access_token': token}


@pytest.mark.parametrize('role', ['ADMIN', 'OPERATOR', 'VIEWER'])
def test_authenticated_read_access(client, db, account, ws_environment, role):
    account.role = role
    db.commit()
    token = issue_token(account.id, 'access', ws_environment)
    with client.websocket_connect(PATH, headers={'origin': ORIGIN}) as socket:
        socket.send_json(frame(token))
        reply = socket.receive_json()
        assert set(reply) == {'type', 'expires_at'} and reply['type'] == 'authenticated'
        assert datetime.fromisoformat(reply['expires_at']).utcoffset().total_seconds() == 0
        assert token not in json.dumps(reply)
        # No application commands (including authentication replacement) in 7.1.
        socket.send_json(frame(token))
        with pytest.raises(WebSocketDisconnect) as caught:
            socket.receive_json()
        assert caught.value.code == 1008


@pytest.mark.parametrize('case', ['refresh', 'expired', 'invalid', 'inactive', 'deleted', 'signature'])
def test_unauthorized_never_receives_ack(client, db, account, ws_environment, case, caplog):
    token = issue_token(account.id, 'refresh' if case == 'refresh' else 'access', ws_environment)
    if case == 'invalid': token = 'invalid-secret-token'
    if case == 'inactive': account.is_active = False
    if case == 'deleted': db.delete(account)
    if case in ('expired', 'signature'):
        token = jwt.encode({'sub': str(account.id), 'iat': int(time.time()) - 60,
                            'exp': int(time.time()) + (-1 if case == 'expired' else 60),
                            'token_type': 'access'},
                           ws_environment.secret if case == 'expired' else 'wrong-key-' * 8,
                           algorithm='HS256')
    db.commit()
    with client.websocket_connect(PATH, headers={'origin': ORIGIN}) as socket:
        socket.send_json(frame(token))
        with pytest.raises(WebSocketDisconnect) as caught:
            socket.receive_json()
        assert caught.value.code == 4401
    assert token not in caplog.text


@pytest.mark.parametrize('origin', [None, 'null', 'https://evil.invalid', ORIGIN + '.evil.invalid'])
def test_origin_required_before_accept(client, origin):
    with pytest.raises(WebSocketDisconnect) as caught:
        with client.websocket_connect(PATH, headers={} if origin is None else {'origin': origin}):
            pytest.fail('Must reject origin before accepting')
    assert caught.value.code == 1008


def test_no_tokens_in_url(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(PATH + '?access_token=forbidden', headers={'origin': ORIGIN}):
            pytest.fail('Query authentication must not be accepted')


@pytest.mark.parametrize('payload,code', [
    ('not-json', 1008), ('[]', 1008), ('{}', 1008),
    ('{"type":"authenticate","access_token":"x","password":"secret"}', 1008),
    ('{"type":"authenticate","access_token":42}', 1008),
    ('{"type":"authenticate","access_token":""}', 1008),
    ('x' * 4097, 1009), (b'binary-frame', 1003),
])
def test_bad_first_message(client, payload, code):
    with client.websocket_connect(PATH, headers={'origin': ORIGIN}) as socket:
        if isinstance(payload, bytes): socket.send_bytes(payload)
        else: socket.send_text(payload)
        with pytest.raises(WebSocketDisconnect) as caught:
            socket.receive_json()
        assert caught.value.code == code


def test_authentication_deadline(client):
    with client.websocket_connect(PATH, headers={'origin': ORIGIN}) as socket:
        with pytest.raises(WebSocketDisconnect) as caught:
            socket.receive_json()
        assert caught.value.code == 4408


def test_idle_connection_expires(client, account, ws_environment):
    now = int(time.time())
    token = jwt.encode({'sub': str(account.id), 'iat': now - 1, 'exp': now + 2,
                        'token_type': 'access'}, ws_environment.secret, algorithm='HS256')
    with client.websocket_connect(PATH, headers={'origin': ORIGIN}) as socket:
        socket.send_json(frame(token))
        assert socket.receive_json()['type'] == 'authenticated'
        with pytest.raises(WebSocketDisconnect) as caught:
            socket.receive_json()
        assert caught.value.code == 4401


def test_db_failure_is_generic(client, monkeypatch, caplog):
    def broken(token):
        raise RuntimeError('password-or-token-must-not-leak')
    monkeypatch.setattr('app.api.websocket.authenticate', broken)
    with client.websocket_connect(PATH, headers={'origin': ORIGIN}) as socket:
        socket.send_json(frame('fake-token'))
        with pytest.raises(WebSocketDisconnect) as caught:
            socket.receive_json()
        assert caught.value.code == 1011
    assert 'password-or-token-must-not-leak' not in caplog.text


@pytest.mark.parametrize('action', ['inactive', 'delete', 'expired'])
def test_revalidate_before_each_send(client, db, account, ws_environment, action):
    principal = auth.authenticate(issue_token(account.id, 'access', ws_environment))
    if action == 'inactive': account.is_active = False
    if action == 'delete': db.delete(account)
    if action == 'expired': principal = Principal(account.id, int(time.time()) - 1)
    db.commit()
    socket = AsyncMock()
    connection = AuthenticatedConnection(socket, principal, websocket_settings())
    with pytest.raises(InvalidCredentials):
        asyncio.run(connection.send(AuthenticatedMessage(expires_at=datetime.now(timezone.utc))))
    socket.send_json.assert_not_awaited()


def test_role_is_read_again_without_cached_orm_user(client, db, account, ws_environment, monkeypatch):
    principal = auth.authenticate(issue_token(account.id, 'access', ws_environment))
    # Simulate an unpermitted future role without violating the database CHECK.
    from types import SimpleNamespace
    monkeypatch.setattr(auth, 'by_id', lambda *args: SimpleNamespace(is_active=True, role='UNPERMITTED'))
    with pytest.raises(ForbiddenUser):
        auth.revalidate(principal)


def test_send_timeout_does_not_wait_forever(monkeypatch):
    monkeypatch.setattr('app.websocket.connection.revalidate', lambda p: None)
    async def blocked(*args):
        await asyncio.Event().wait()
    socket = AsyncMock()
    socket.send_json.side_effect = blocked
    connection = AuthenticatedConnection(socket, Principal(1, int(time.time()) + 60),
        WebSocketSettings(1, 0.01, 4096, frozenset([ORIGIN]), 2))
    with pytest.raises(TimeoutError):
        asyncio.run(connection.send(AuthenticatedMessage(expires_at=datetime.now(timezone.utc))))
    socket.send_json.assert_awaited_once()


def test_expiry_during_blocked_send_is_auth_expiry(monkeypatch):
    monkeypatch.setattr('app.websocket.connection.revalidate', lambda p: None)
    async def blocked(*args):
        await asyncio.Event().wait()
    socket = AsyncMock()
    socket.send_json.side_effect = blocked
    connection = AuthenticatedConnection(socket, Principal(1, int(time.time()) + 1),
        WebSocketSettings(1, 5, 4096, frozenset([ORIGIN]), 2))
    with pytest.raises(InvalidCredentials):
        asyncio.run(connection.send(AuthenticatedMessage(expires_at=datetime.now(timezone.utc))))
    socket.send_json.assert_awaited_once()


@pytest.mark.parametrize('name,value', [
    ('WS_AUTH_TIMEOUT_SECONDS', ''), ('WS_AUTH_TIMEOUT_SECONDS', 'nan'),
    ('WS_SEND_TIMEOUT_SECONDS', '0'), ('WS_SEND_TIMEOUT_SECONDS', 'inf'),
    ('WS_MAX_MESSAGE_BYTES', '-1'), ('WS_MAX_MESSAGE_BYTES', '1.2'),
    ('WS_CLIENT_QUEUE_SIZE', ''), ('WS_CLIENT_QUEUE_SIZE', '0'),
    ('WS_CLIENT_QUEUE_SIZE', '-1'), ('WS_CLIENT_QUEUE_SIZE', '1.2'),
    ('WS_ALLOWED_ORIGINS', '[]'), ('WS_ALLOWED_ORIGINS', '"*"'),
    ('WS_ALLOWED_ORIGINS', '["*"]'), ('WS_ALLOWED_ORIGINS', '["null"]'),
    ('WS_ALLOWED_ORIGINS', '["http://user:secret@localhost"]'),
    ('WS_ALLOWED_ORIGINS', '["http://localhost/path"]'),
    ('WS_ALLOWED_ORIGINS', '["http://localhost:0"]'),
    ('WS_ALLOWED_ORIGINS', '["http://localhost?token=secret"]'),
])
def test_explicit_configuration_validation(ws_environment, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(WebSocketConfigurationError) as caught:
        websocket_settings()
    assert 'secret' not in str(caught.value)


def test_notification_contract_uses_internal_ids_and_utc():
    data = dict(type='FAULT_CONFIRMED', event_id=1, uuid=uuid4(), machine_id=2,
                timestamp='2026-11-07T08:00:00-04:00', severity='CRITICAL')
    message = EventNotification(**data).model_dump(mode='json')
    assert message['machine_id'] == 2 and message['timestamp'] == '2026-11-07T12:00:00Z'
    for replacement in ({'machine_id': 'MACHINE-001'}, {'type': 'COLOR_RED'}, {'password': 'secret'}):
        with pytest.raises(ValidationError): EventNotification(**(data | replacement))
    assert 'secret' not in repr(AuthenticationMessage(type='authenticate', access_token='secret'))


def test_transport_logs_strip_queries_and_disable_frame_debug():
    filter_ = TransportLogFilter()
    record = logging.LogRecord('uvicorn.error', logging.INFO, '', 0,
        '%s accepted', (PATH + '?access_token=secret-token',), None)
    assert filter_.filter(record)
    assert 'secret-token' not in record.getMessage() and '[REDACTED]' in record.getMessage()
    debug = logging.LogRecord('uvicorn.error', logging.DEBUG, '', 0, 'frame secret-token', (), None)
    assert not filter_.filter(debug)


def test_transport_filter_preserves_http_access_formatter():
    record = logging.LogRecord('uvicorn.access', logging.INFO, '', 0,
        '%s - "%s %s HTTP/%s" %d',
        ('127.0.0.1:12345', 'GET', PATH + '?access_token=secret-token', '1.1', 403), None)
    assert TransportLogFilter().filter(record)
    formatted = AccessFormatter('%(client_addr)s %(request_line)s %(status_code)s', use_colors=False).format(record)
    assert 'GET ' + PATH in formatted and '403' in formatted
    assert 'secret-token' not in formatted and '[REDACTED]' in formatted

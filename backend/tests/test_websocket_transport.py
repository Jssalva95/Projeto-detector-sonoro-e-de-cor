"""Real local Uvicorn/WebSocket sockets, isolated PostgreSQL and test-only JWTs."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from uuid import uuid4

import jwt
import pytest
from sqlalchemy import text
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import connect

from app.database.session import database_url
from app.models import User
from app.security import issue_token
from test_event_concurrency import concurrent_database
from test_websocket import ORIGIN, PATH, frame, ws_environment


@pytest.fixture
def live_server(concurrent_database, ws_environment, request):
    sessions, _, ids = concurrent_database
    with sessions() as session:
        schema = session.scalar(text('SELECT current_schema()'))
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    environment = os.environ.copy()
    environment.update(
        DATABASE_URL=database_url().update_query_dict({'options': '-csearch_path=' + schema}).render_as_string(hide_password=False),
        # Allow cold PostgreSQL authentication in integration tests. Only the
        # deadline test requests 0.3s; these are test limits, not server defaults.
        BACKEND_PORT=str(port), WS_AUTH_TIMEOUT_SECONDS=str(getattr(request, 'param', 2)),
        EMAIL_ENABLED='false', TELEGRAM_ENABLED='false',
        DEVICE_API_KEY='live-publication-test-key',
    )
    with tempfile.TemporaryFile() as logs:
        process = subprocess.Popen([sys.executable, '-m', 'app.server'], env=environment,
                                   stdout=logs, stderr=logs)
        try:
            for _ in range(100):
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=1) as reply:
                        assert reply.status == 200
                    break
                except OSError:
                    if process.poll() is not None:
                        pytest.fail('Local server failed to start; no environment values logged')
                    time.sleep(0.1)
            else:
                pytest.fail('Local server startup timed out')
            yield f'ws://127.0.0.1:{port}' + PATH, ids[1][0], ws_environment, logs
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def open_socket(url, origin=ORIGIN):
    return connect(url, origin=origin, proxy=None, open_timeout=3, close_timeout=1)


def test_live_committed_broadcast_and_replay(live_server, concurrent_database):
    url, user_id, settings, _ = live_server
    sessions, payload, _ = concurrent_database
    endpoint = url.replace('ws://', 'http://').replace(PATH, '/api/v1/events')
    payload = payload | {'uuid': str(payload['uuid'])}

    def submit():
        request = urllib.request.Request(endpoint, data=json.dumps(payload).encode(),
                    headers={'Content-Type': 'application/json', 'X-API-Key': 'live-publication-test-key'})
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read())

    with open_socket(url) as first, open_socket(url) as second:
        for socket_ in (first, second):
            socket_.send(json.dumps(frame(issue_token(user_id, 'access', settings))))
            assert json.loads(socket_.recv(timeout=3))['type'] == 'authenticated'
        status, row = submit()
        assert status == 201
        notices = [json.loads(socket_.recv(timeout=3)) for socket_ in (first, second)]
        assert notices[0] == notices[1]
        assert notices[0]['event_id'] == row['id']
        assert notices[0]['uuid'] == payload['uuid']
        assert submit()[0] == 200
        for socket_ in (first, second):
            with pytest.raises(TimeoutError):
                socket_.recv(timeout=0.1)
        with sessions() as session:
            session.get(User, user_id).is_active = False
        payload['uuid'] = str(uuid4())
        assert submit()[0] == 201
        for socket_ in (first, second):
            with pytest.raises(ConnectionClosed) as caught:
                socket_.recv(timeout=3)
            assert caught.value.rcvd.code == 4401


def test_live_authentication_and_independent_connections(live_server):
    url, user_id, settings, logs = live_server
    access = issue_token(user_id, 'access', settings)
    refresh = issue_token(user_id, 'refresh', settings)
    with open_socket(url) as first, open_socket(url) as second:
        first.send(json.dumps(frame(access)))
        assert json.loads(first.recv(timeout=3))['type'] == 'authenticated'
        second.send(json.dumps(frame(refresh)))
        with pytest.raises(ConnectionClosed) as caught:
            second.recv(timeout=3)
        assert caught.value.rcvd.code == 4401
        # Closing another connection doesn't close the first; application commands are rejected.
        first.send('unexpected-command')
        with pytest.raises(ConnectionClosed) as caught:
            first.recv(timeout=3)
        assert caught.value.rcvd.code == 1008
    logs.seek(0)
    output = logs.read().decode()
    assert access not in output and refresh not in output
    assert 'Logging error' not in output and 'Traceback' not in output


def test_live_origin_rejection_and_query_redaction(live_server):
    url, *_ , logs = live_server
    for origin in (None, 'https://evil.invalid'):
        with pytest.raises(InvalidStatus) as caught:
            open_socket(url, origin)
        assert caught.value.response.status_code == 403
    with pytest.raises(InvalidStatus) as caught:
        open_socket(url + '?access_token=query-secret-must-not-leak')
    assert caught.value.response.status_code == 403
    logs.seek(0)
    assert 'query-secret-must-not-leak' not in logs.read().decode()


@pytest.mark.parametrize('live_server', [0.3], indirect=True)
def test_live_transport_size_binary_and_auth_deadline(live_server):
    url, *_ = live_server
    for payload, expected in [('x' * 4097, 1009), (b'binary', 1003), (None, 4408)]:
        with open_socket(url) as socket_:
            if payload is not None: socket_.send(payload)
            with pytest.raises(ConnectionClosed) as caught:
                socket_.recv(timeout=3)
            assert caught.value.rcvd.code == expected


def test_live_expiry_without_incoming_messages(live_server):
    url, user_id, settings, _ = live_server
    now = int(time.time())
    token = jwt.encode({'sub': str(user_id), 'iat': now - 1, 'exp': now + 2,
                        'token_type': 'access'}, settings.secret, algorithm='HS256')
    with open_socket(url) as socket_:
        socket_.send(json.dumps(frame(token)))
        assert json.loads(socket_.recv(timeout=3))['type'] == 'authenticated'
        with pytest.raises(ConnectionClosed) as caught:
            socket_.recv(timeout=3)
        assert caught.value.rcvd.code == 4401

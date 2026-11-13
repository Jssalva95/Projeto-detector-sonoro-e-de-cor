"""Phase 7 closure: real HTTP/WS transport and REST resynchronization."""

import json
import urllib.request
from uuid import uuid4

import pytest

from app.security import issue_token
from test_event_concurrency import concurrent_database
from test_websocket import PATH, frame, ws_environment
from test_websocket_transport import live_server, open_socket


def request(url, path, *, payload=None, token=None, method=None):
    base = url.replace('ws://', 'http://').removesuffix(PATH)
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    else:
        headers['X-API-Key'] = 'live-publication-test-key'
    data = None if payload is None else json.dumps(payload).encode()
    with urllib.request.urlopen(urllib.request.Request(base + path, data=data, headers=headers, method=method),
                                timeout=3) as response:
        return response.status, json.loads(response.read())


def authenticate(socket, token):
    socket.send(json.dumps(frame(token)))
    assert json.loads(socket.recv(timeout=3))['type'] == 'authenticated'


@pytest.mark.parametrize('kind', ['FAULT_CONFIRMED', 'FAULT_RECOVERED', 'DEVICE_OFFLINE',
                                 'DEVICE_ONLINE', 'COLOR_RED', 'ALARM_SOUND'])
def test_live_event_contract_and_rest_visibility(live_server, concurrent_database, kind):
    url, user_id, settings, _ = live_server
    _, values, _ = concurrent_database
    token = issue_token(user_id, 'access', settings)
    values = values | {'uuid': str(values['uuid']), 'event_type': kind}
    with open_socket(url) as socket:
        authenticate(socket, token)
        status, row = request(url, '/api/v1/events', payload=values)
        assert status == 201
        if kind in {'COLOR_RED', 'ALARM_SOUND'}:
            with pytest.raises(TimeoutError):
                socket.recv(timeout=0.1)
        else:
            notice = json.loads(socket.recv(timeout=3))
            assert notice == dict(type=kind, event_id=row['id'], uuid=row['uuid'],
                                  machine_id=row['machine_id'], timestamp=row['started_at'],
                                  severity=row['severity'])
        status, persisted = request(url, f"/api/v1/events/{row['id']}", token=token)
        assert status == 200 and persisted == row
        # Acknowledging changes REST metadata but is not a new occurrence.
        status, acknowledged = request(url, f"/api/v1/events/{row['id']}/acknowledge",
                                       method='POST', token=token)
        assert status == 200 and acknowledged['acknowledged'] is True
        with pytest.raises(TimeoutError):
            socket.recv(timeout=0.1)


def test_live_reconnect_rest_recovery_without_replay(live_server, concurrent_database):
    url, user_id, settings, _ = live_server
    _, values, _ = concurrent_database
    token = issue_token(user_id, 'access', settings)
    values = values | {'uuid': str(values['uuid'])}
    with open_socket(url) as first:
        authenticate(first, token)
        assert request(url, '/api/v1/events', payload=values)[0] == 201
        assert json.loads(first.recv(timeout=3))['uuid'] == values['uuid']

    missing = values | {'uuid': str(uuid4()), 'event_type': 'DEVICE_OFFLINE'}
    status, missed_row = request(url, '/api/v1/events', payload=missing)
    assert status == 201
    with open_socket(url) as reconnected:
        authenticate(reconnected, token)
        # There is no server-side replay; history is obtained through REST.
        with pytest.raises(TimeoutError):
            reconnected.recv(timeout=0.1)
        status, history = request(url, '/api/v1/events?limit=200&offset=0', token=token)
        assert status == 200
        assert {row['uuid'] for row in history} == {values['uuid'], missing['uuid']}
        assert missed_row in history
        online = values | {'uuid': str(uuid4()), 'event_type': 'DEVICE_ONLINE'}
        assert request(url, '/api/v1/events', payload=online)[0] == 201
        assert json.loads(reconnected.recv(timeout=3))['uuid'] == online['uuid']
        with pytest.raises(TimeoutError):
            reconnected.recv(timeout=0.1)

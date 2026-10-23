"""Event HTTP contracts on real PostgreSQL in rollback-isolated schemas."""

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.main import app
from app.models import Alert, Device, Event, Machine, SensorReading, User
from app.security import issue_token
from test_auth import settings, user
from test_domain import db
from test_equipment import KEY, admin, client, device, machine, machine_payload

PATH = "/api/v1/events"
KEY_HEADER = {"X-API-Key": KEY}


@pytest.fixture
def payload(machine, device):
    return dict(uuid=str(uuid4()), machine_id=machine["id"], device_id=device["id"],
                event_type="FAULT_CONFIRMED", severity="CRITICAL",
                started_at="2026-10-22T08:00:00-04:00", message="Test occurrence")


def post(client, payload, **changes):
    return client.post(PATH, headers=KEY_HEADER, json=payload | changes)


def test_create_roundtrip_no_side_effects(client, admin, db, payload, machine, device):
    response = post(client, payload, sound_amplitude=4095, sound_duration_ms=0)
    assert response.status_code == 201
    row = response.json()
    assert row["started_at"] == "2026-10-22T12:00:00Z"
    assert not row["acknowledged"] and row["acknowledged_by"] is None and row["acknowledged_at"] is None
    assert row["ended_at"] is None and row["sound_amplitude"] == 4095
    db.expire_all()
    assert str(db.get(Event, row["id"]).uuid) == payload["uuid"]
    assert client.get(PATH + f"/{row['id']}", headers=admin).json() == row
    assert client.get(PATH, headers=admin).json() == [row]
    assert db.get(Machine, machine["id"]).status == machine["status"]
    assert db.get(Device, device["id"]).last_seen_at is None
    for model in (Alert, SensorReading):
        assert db.scalar(select(func.count()).select_from(model)) == 0


def test_retransmission_normalized_optional_null_and_acknowledgment(client, admin, db, payload):
    original = post(client, payload).json()
    response = post(client, payload, started_at="2026-10-22T12:00:00Z", color=None,
                    ended_at=None, sound_detected=None, sound_amplitude=None, sound_duration_ms=None)
    assert response.status_code == 200 and response.json() == original
    ack = client.post(PATH + f"/{original['id']}/acknowledge", headers=admin)
    assert ack.status_code == 200
    replay = post(client, payload)
    assert replay.status_code == 200 and replay.json() == ack.json()
    assert db.scalar(select(func.count()).select_from(Event)) == 1


@pytest.mark.parametrize("changes", [
    {"message": "different"}, {"severity": "INFO"}, {"event_type": "COLOR_RED"},
    {"started_at": "2026-10-22T12:00:01Z"}, {"ended_at": "2026-10-22T13:00:00Z"},
    {"color": "RED"}, {"sound_detected": False}, {"sound_amplitude": 0}, {"sound_duration_ms": 0},
])
def test_conflicting_uuid_preserves_occurrence(client, admin, db, payload, changes):
    original = post(client, payload).json()
    assert post(client, payload, **changes).status_code == 409
    assert client.get(PATH, headers=admin).json() == [original]
    assert post(client, payload, uuid=str(uuid4())).status_code == 201


def test_associations_inactivity_history(client, admin, db, payload, device):
    for field in ("machine_id", "device_id"):
        assert post(client, payload, **{field: 9223372036854775807}).status_code == 404
    other = client.post('/api/v1/machines', headers=admin, json=machine_payload('other')).json()
    assert post(client, payload, machine_id=other["id"]).status_code == 409
    original = post(client, payload).json()
    assert client.patch(f"/api/v1/devices/{device['id']}", headers=admin,
                        json={"machine_id": other["id"]}).status_code == 200
    assert post(client, payload).status_code == 200
    assert post(client, payload, uuid=str(uuid4())).status_code == 409
    assert post(client, payload, uuid=str(uuid4()), machine_id=other["id"]).status_code == 201
    assert client.get(PATH + f"/{original['id']}", headers=admin).json() == original
    assert client.patch(f"/api/v1/devices/{device['id']}", headers=admin,
                        json={"is_active": False}).status_code == 200
    assert post(client, payload).status_code == 403
    assert post(client, payload, uuid=str(uuid4()), machine_id=other["id"]).status_code == 403


@pytest.mark.parametrize("changes", [
    {"uuid": "invalid"}, {"uuid": None}, {"machine_id": 0}, {"device_id": 9223372036854775808},
    {"event_type": "INVALID"}, {"severity": "HIGH"}, {"color": "GREEN"},
    {"started_at": "2026-10-22T12:00:00"}, {"ended_at": "2026-10-22T11:00:00Z"},
    {"sound_duration_ms": -1}, {"sound_duration_ms": 9223372036854775808},
    {"sound_amplitude": "NaN"}, {"sound_amplitude": "Infinity"}, {"sound_amplitude": "-Infinity"},
    {"sound_amplitude": "1e309"}, {"message": None}, {"id": 1}, {"unknown": True},
    {"created_at": "2026-10-22T12:00:00Z"}, {"acknowledged": False},
    {"acknowledged_by": 1}, {"acknowledged_at": None},
])
def test_invalid_input_no_persistence(client, db, payload, changes):
    assert post(client, payload, **changes).status_code == 422
    assert db.scalar(select(func.count()).select_from(Event)) == 0


def test_numeric_overflow_uuid_required_and_finite_negative(client, db, payload):
    body = json.dumps(payload | {"sound_amplitude": "overflow"}).replace('"overflow"', '1e309')
    assert client.post(PATH, headers=KEY_HEADER | {"Content-Type": "application/json"}, content=body).status_code == 422
    missing = payload.copy()
    del missing["uuid"]
    assert post(client, missing).status_code == 422
    assert db.scalar(select(func.count()).select_from(Event)) == 0
    assert post(client, payload, sound_amplitude=-10).status_code == 201


@pytest.mark.parametrize("event_type", ["COLOR_RED", "ALARM_SOUND", "FAULT_CONFIRMED", "FAULT_RECOVERED", "DEVICE_OFFLINE", "DEVICE_ONLINE"])
def test_types_do_not_infer_severity(client, payload, event_type):
    for severity in ("INFO", "WARNING", "CRITICAL"):
        response = post(client, payload, uuid=str(uuid4()), event_type=event_type, severity=severity)
        assert response.status_code == 201 and response.json()["severity"] == severity


def test_acknowledge_preserves_first_user_time_and_end(client, admin, db, user, settings, payload):
    row = post(client, payload).json()
    before = datetime.now(timezone.utc)
    response = client.post(PATH + f"/{row['id']}/acknowledge", headers=admin)
    assert response.status_code == 200
    first = response.json()
    assert first["acknowledged"] and first["acknowledged_by"] == user.id
    assert before <= datetime.fromisoformat(first["acknowledged_at"].replace('Z', '+00:00')) <= datetime.now(timezone.utc)
    assert first["ended_at"] is None
    other = User(name="Other", email="other@example.invalid", password_hash="fixture", role="OPERATOR")
    db.add(other)
    db.commit()
    auth = {"Authorization": "Bearer " + issue_token(other.id, "access", settings)}
    assert client.post(PATH + f"/{row['id']}/acknowledge", headers=auth).json() == first
    assert client.get(PATH + f"/{row['id']}", headers=admin).json() == first
    for body in ({}, {"acknowledged_by": other.id}, {"acknowledged_at": row["started_at"]}):
        assert client.post(PATH + f"/{row['id']}/acknowledge", headers=admin, json=body).status_code == 422


@pytest.mark.parametrize("role,expected", [("ADMIN", 200), ("OPERATOR", 200), ("VIEWER", 403)])
def test_roles(client, admin, db, user, payload, role, expected):
    row = post(client, payload).json()
    user.role = role
    db.commit()
    assert client.get(PATH, headers=admin).status_code == 200
    assert client.get(PATH + f"/{row['id']}", headers=admin).status_code == 200
    assert client.post(PATH + f"/{row['id']}/acknowledge", headers=admin).status_code == expected
    assert client.post(PATH, headers=admin, json=payload).status_code == 401


def test_credentials_and_inactive_user(client, admin, db, user, settings, payload, monkeypatch, caplog):
    row = post(client, payload).json()
    refresh = {"Authorization": "Bearer " + issue_token(user.id, 'refresh', settings)}
    paths = [("get", PATH), ("get", PATH + f"/{row['id']}"),
             ("post", PATH + f"/{row['id']}/acknowledge")]
    for method, path in paths:
        for headers in ({}, KEY_HEADER, refresh):
            assert client.request(method, path, headers=headers).status_code == 401
    for headers in ({}, admin, refresh, {"X-API-Key": "wrong"}):
        assert client.post(PATH, headers=headers, json=payload).status_code == 401
    user.is_active = False
    db.commit()
    for method, path in paths:
        assert client.request(method, path, headers=admin).status_code == 401
    monkeypatch.delenv('DEVICE_API_KEY')
    assert post(client, payload).status_code == 503
    assert KEY not in caplog.text


def test_filters_and_inclusive_dates(client, admin, payload):
    rows = []
    for hour, kind, severity in ((11, 'COLOR_RED', 'INFO'), (12, 'ALARM_SOUND', 'WARNING'), (13, 'FAULT_CONFIRMED', 'CRITICAL')):
        rows.append(post(client, payload, uuid=str(uuid4()), started_at=f'2026-10-22T{hour}:00:00Z',
                         event_type=kind, severity=severity).json())
    rows[1] = client.post(PATH + f"/{rows[1]['id']}/acknowledge", headers=admin).json()
    def query(**params):
        response = client.get(PATH, headers=admin, params=params)
        assert response.status_code == 200
        return response.json()
    assert query() == rows[::-1]
    assert query(acknowledged='false') == [rows[2], rows[0]]
    assert query(acknowledged='true') == [rows[1]]
    assert query(event_type='COLOR_RED') == [rows[0]]
    assert query(severity='CRITICAL') == [rows[2]]
    assert query(start_date='2026-10-22T08:00:00-04:00', end_date='2026-10-22T13:00:00Z') == [rows[2], rows[1]]
    assert query(machine_id=payload['machine_id'], event_type='ALARM_SOUND', severity='WARNING',
                 acknowledged='true', start_date='2026-10-22T12:00:00Z', end_date='2026-10-22T12:00:00Z') == [rows[1]]
    assert query(machine_id=9223372036854775807) == []
    assert query(event_type='COLOR_RED', severity='CRITICAL') == []
    assert query(offset=9223372036854775807) == []


def test_pagination_default_limit_and_timestamp_ties(client, admin, payload):
    ids = [post(client, payload, uuid=str(uuid4())).json()['id'] for _ in range(51)][::-1]
    def query(**params):
        response = client.get(PATH, headers=admin, params=params)
        assert response.status_code == 200
        return [row['id'] for row in response.json()]
    assert query() == ids[:50]
    assert query(limit=200) == ids
    assert query(limit=25) + query(limit=25, offset=25) + query(limit=25, offset=50) == ids


@pytest.mark.parametrize('params', [
    {'limit': 0}, {'limit': 201}, {'offset': -1}, {'offset': 9223372036854775808},
    {'machine_id': 0}, {'severity': 'HIGH'}, {'event_type': 'INVALID'}, {'acknowledged': 'invalid'},
    {'start_date': '2026-10-22T12:00:00'}, {'start_date': '2026-10-23T00:00:00Z', 'end_date': '2026-10-22T00:00:00Z'},
])
def test_invalid_queries(client, admin, params):
    assert client.get(PATH, headers=admin, params=params).status_code == 422


def test_missing_ids_and_absent_mutations(client, admin, payload):
    for method, suffix in (('get', ''), ('post', '/acknowledge')):
        assert client.request(method, PATH + '/9223372036854775807' + suffix, headers=admin).status_code == 404
        for id in ('0', '-1', 'invalid', '9223372036854775808'):
            assert client.request(method, PATH + '/' + id + suffix, headers=admin).status_code == 422
    row = post(client, payload).json()
    for method in ('put', 'patch', 'delete'):
        assert client.request(method, PATH + f"/{row['id']}", headers=admin).status_code == 405


def test_event_openapi_contract():
    schema = app.openapi()
    paths = schema['paths']
    assert set(paths[PATH]) == {'get', 'post'}
    assert set(paths[PATH + '/{id}']) == {'get'}
    assert set(paths[PATH + '/{id}/acknowledge']) == {'post'}
    assert paths[PATH]['post']['security'] == [{'APIKeyHeader': []}]
    for path, method in ((PATH, 'get'), (PATH + '/{id}', 'get'), (PATH + '/{id}/acknowledge', 'post')):
        assert paths[path][method]['security'] == [{'HTTPBearer': []}]
    assert {'200', '201'} <= set(paths[PATH]['post']['responses'])
    fields = schema['components']['schemas']['EventRequest']['properties']
    assert not {'id', 'created_at', 'acknowledged', 'acknowledged_by', 'acknowledged_at'} & set(fields)
    assert {item['name'] for item in paths[PATH]['get']['parameters']} == {
        'machine_id', 'event_type', 'severity', 'acknowledged', 'start_date', 'end_date', 'limit', 'offset'}

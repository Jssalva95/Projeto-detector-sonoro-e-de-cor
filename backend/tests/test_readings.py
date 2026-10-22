"""Telemetry HTTP contracts against PostgreSQL, rolled back after every test."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.main import app
from app.models import Alert, Device, Event, Machine, SensorReading
from app.security import issue_token
from test_auth import settings, user
from test_domain import db
from test_equipment import KEY, admin, client, device, machine, machine_payload

PATH = "/api/v1/readings"
KEY_HEADER = {"X-API-Key": KEY}


@pytest.fixture
def payload(machine, device):
    return dict(uuid=str(uuid4()), machine_id=machine["id"], device_id=device["id"],
                timestamp="2026-10-20T08:00:00-04:00", color="RED", red_value=812,
                green_value=190, blue_value=221, color_confidence=0.8,
                sound_detected=True, sound_amplitude=4095, sound_duration_ms=123)


def post(client, payload, **changes):
    return client.post(PATH, headers=KEY_HEADER, json=payload | changes)


def test_roundtrip_utc_raw_values_no_side_effects(client, admin, db, payload, device, machine):
    response = post(client, payload)
    assert response.status_code == 201
    row = response.json()
    assert row["uuid"] == payload["uuid"] and row["timestamp"] == "2026-10-20T12:00:00Z"
    assert row["sound_amplitude"] == 4095 and row["red_value"] == 812
    assert row["sound_trigger"] is None
    created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
    # PostgreSQL now() is the transaction start, including the isolated fixture.
    assert created <= datetime.now(timezone.utc)
    db.expire_all()
    assert db.get(SensorReading, row["id"]).uuid == UUID(payload["uuid"])
    assert client.get(PATH + f"/{row['id']}", headers=admin).json() == row
    assert client.get(PATH, headers=admin).json() == [row]
    stored_device = db.get(Device, device["id"])
    assert stored_device.last_seen_at is None
    assert stored_device.firmware_version == device["firmware_version"]
    assert stored_device.is_active is True
    assert db.get(Machine, machine["id"]).status == machine["status"]
    for model in (Event, Alert):
        assert db.scalar(select(func.count()).select_from(model)) == 0


def test_duplicate_uuid_rollback_preserves_original(client, admin, db, payload):
    original = post(client, payload).json()
    response = post(client, payload, sound_amplitude=77)
    assert response.status_code == 409
    assert response.json() == {"detail": "Reading UUID already exists"}
    assert client.get(PATH, headers=admin).json() == [original]
    assert post(client, payload, uuid=str(uuid4())).status_code == 201
    assert db.scalar(select(func.count()).select_from(SensorReading)) == 2


def test_missing_inactive_and_mismatch(client, admin, db, payload, device):
    for field in ("machine_id", "device_id"):
        assert post(client, payload, **{field: 9223372036854775807}).status_code == 404
    other = client.post("/api/v1/machines", headers=admin, json=machine_payload("other")).json()
    assert post(client, payload, machine_id=other["id"]).status_code == 409
    assert client.patch(f"/api/v1/devices/{device['id']}", headers=admin,
                        json={"is_active": False}).status_code == 200
    assert post(client, payload).status_code == 403
    assert db.scalar(select(func.count()).select_from(SensorReading)) == 0


def test_reassociation_preserves_history_rejects_late_old_reading(client, admin, payload, device):
    original = post(client, payload).json()
    other = client.post("/api/v1/machines", headers=admin, json=machine_payload("other")).json()
    assert client.patch(f"/api/v1/devices/{device['id']}", headers=admin,
                        json={"machine_id": other["id"]}).status_code == 200
    assert post(client, payload, uuid=str(uuid4())).status_code == 409
    assert post(client, payload, uuid=str(uuid4()), machine_id=other["id"]).status_code == 201
    assert client.get(PATH + f"/{original['id']}", headers=admin).json() == original
    assert client.get(PATH, headers=admin, params={"machine_id": payload["machine_id"]}).json() == [original]


@pytest.mark.parametrize("changes", [
    {"uuid": "invalid"}, {"uuid": None}, {"timestamp": "2026-10-20T08:00:00"},
    {"color": "GREEN"}, {"red_value": -1}, {"red_value": 2147483648},
    {"color_confidence": 1.01}, {"color_confidence": -0.01},
    {"sound_duration_ms": -1}, {"sound_duration_ms": 9223372036854775808},
    {"machine_id": 0}, {"device_id": 9223372036854775808}, {"sound_amplitude": None},
    {"id": 12}, {"created_at": "2026-10-20T00:00:00Z"}, {"unknown": 1},
])
def test_invalid_payload_no_insert(client, db, payload, changes):
    assert post(client, payload, **changes).status_code == 422
    assert db.scalar(select(func.count()).select_from(SensorReading)) == 0


def test_uuid_required_nullable_trigger_and_raw_amplitude(client, payload):
    missing = payload.copy()
    del missing["uuid"]
    assert post(client, missing).status_code == 422
    for trigger, amplitude in ((None, -10), (False, 4095), (True, 0)):
        response = post(client, payload, uuid=str(uuid4()), sound_trigger=trigger,
                        sound_amplitude=amplitude)
        assert response.status_code == 201
        assert response.json()["sound_trigger"] is trigger
        assert response.json()["sound_amplitude"] == amplitude


def test_filters_inclusive_combined_false_and_empty(client, admin, payload):
    rows = []
    for hour, color, sound in ((11, "BLUE", False), (12, "RED", True),
                                (13, "UNKNOWN", False), (14, "RED", False)):
        response = post(client, payload, uuid=str(uuid4()),
                        timestamp=f"2026-10-20T{hour}:00:00Z", color=color, sound_detected=sound)
        assert response.status_code == 201
        rows.append(response.json())
    def query(**params):
        response = client.get(PATH, headers=admin, params=params)
        assert response.status_code == 200
        return response.json()
    assert query() == rows[::-1]
    assert query(color="BLUE") == [rows[0]]
    assert query(sound_detected="false") == [rows[3], rows[2], rows[0]]
    assert query(sound_detected="true") == [rows[1]]
    assert query(start_date="2026-10-20T08:00:00-04:00", end_date="2026-10-20T13:00:00Z") == [rows[2], rows[1]]
    assert query(start_date="2026-10-20T14:00:00Z") == [rows[3]]
    assert query(end_date="2026-10-20T11:00:00Z") == [rows[0]]
    assert query(machine_id=payload["machine_id"], color="RED", sound_detected="false",
                 start_date="2026-10-20T14:00:00Z", end_date="2026-10-20T14:00:00Z") == [rows[3]]
    assert query(machine_id=9223372036854775807) == []
    assert query(color="BLUE", sound_detected="true") == []
    assert query(offset=100) == []


def test_pagination_default_maximum_and_ties(client, admin, payload):
    ids = []
    for _ in range(51):
        response = post(client, payload, uuid=str(uuid4()))
        assert response.status_code == 201
        ids.append(response.json()["id"])
    expected = ids[::-1]
    def ids_for(**params):
        response = client.get(PATH, headers=admin, params=params)
        assert response.status_code == 200
        return [row["id"] for row in response.json()]
    assert ids_for() == expected[:50]
    assert ids_for(limit=200) == expected
    assert ids_for(limit=25, offset=0) + ids_for(limit=25, offset=25) + ids_for(limit=25, offset=50) == expected


@pytest.mark.parametrize("params", [
    {"limit": 0}, {"limit": 201}, {"limit": "abc"}, {"offset": -1}, {"offset": "1.5"},
    {"machine_id": 0}, {"machine_id": 9223372036854775808}, {"color": "GREEN"},
    {"sound_detected": "invalid"}, {"start_date": "2026-10-20T12:00:00"},
    {"end_date": "invalid"},
    {"start_date": "2026-10-21T00:00:00Z", "end_date": "2026-10-20T00:00:00Z"},
])
def test_invalid_queries(client, admin, params):
    assert client.get(PATH, headers=admin, params=params).status_code == 422


@pytest.mark.parametrize("role", ["ADMIN", "OPERATOR", "VIEWER"])
def test_read_permissions_and_write_requires_key(client, admin, db, user, payload, role):
    row = post(client, payload).json()
    user.role = role
    db.commit()
    assert client.get(PATH, headers=admin).status_code == 200
    assert client.get(PATH + f"/{row['id']}", headers=admin).status_code == 200
    assert client.post(PATH, headers=admin, json=payload).status_code == 401


def test_authentication_boundaries(client, admin, db, user, settings, payload, monkeypatch, caplog):
    row = post(client, payload).json()
    refresh = {"Authorization": "Bearer " + issue_token(user.id, "refresh", settings)}
    for path in (PATH, PATH + f"/{row['id']}"):
        for headers in ({}, KEY_HEADER, refresh, {"Authorization": "Bearer invalid"}):
            assert client.get(path, headers=headers).status_code == 401
    for headers in ({}, admin, refresh, {"X-API-Key": "wrong"}):
        assert client.post(PATH, json=payload, headers=headers).status_code == 401
    user.is_active = False
    db.commit()
    for path in (PATH, PATH + f"/{row['id']}"):
        assert client.get(path, headers=admin).status_code == 401
    monkeypatch.delenv("DEVICE_API_KEY")
    assert post(client, payload).status_code == 503
    assert KEY not in caplog.text


def test_missing_invalid_id_and_no_mutation_routes(client, admin, payload):
    assert client.get(PATH + "/9223372036854775807", headers=admin).status_code == 404
    for identifier in ("0", "-1", "9223372036854775808", "invalid"):
        assert client.get(PATH + "/" + identifier, headers=admin).status_code == 422
    row = post(client, payload).json()
    for method in ("patch", "put", "delete"):
        assert client.request(method, PATH + f"/{row['id']}", headers=admin).status_code == 405


def test_reading_openapi():
    paths = app.openapi()["paths"]
    assert set(paths[PATH]) == {"get", "post"}
    assert set(paths[PATH + "/{id}"]) == {"get"}
    assert paths[PATH]["post"]["security"] == [{"APIKeyHeader": []}]
    assert paths[PATH]["get"]["security"] == [{"HTTPBearer": []}]
    assert paths[PATH + "/{id}"]["get"]["security"] == [{"HTTPBearer": []}]
    params = {p["name"]: p for p in paths[PATH]["get"]["parameters"]}
    assert set(params) == {"machine_id", "start_date", "end_date", "color", "sound_detected", "limit", "offset"}
    assert params["limit"]["schema"]["maximum"] == 200
    assert params["limit"]["schema"]["default"] == 50

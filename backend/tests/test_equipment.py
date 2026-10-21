"""Real routers and PostgreSQL, isolated using the approved migration fixture."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.dependencies import get_session
from app.main import app
from app.models import Device, Event, Machine, SensorReading
from app.security import issue_token
from test_auth import settings, user
from test_domain import db, records

KEY = "isolated-device-key-fixture"
MACHINES = "/api/v1/machines"
DEVICES = "/api/v1/devices"
HEARTBEAT = DEVICES + "/heartbeat"


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setenv("DEVICE_API_KEY", KEY)

    def transactional_session():
        with db.begin_nested():
            yield db

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_session] = transactional_session
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.fixture
def admin(user, settings):
    return {"Authorization": "Bearer " + issue_token(user.id, "access", settings)}


def machine_payload(serial="fixture-machine"):
    return {"serial_number": serial, "name": "Fixture", "block": "Test",
            "corridor": "Test", "description": "Test description", "status": "MAINTENANCE"}


@pytest.fixture
def machine(client, admin):
    response = client.post(MACHINES, json=machine_payload(), headers=admin)
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def device(client, admin, machine):
    response = client.post(DEVICES, headers=admin, json={
        "machine_id": machine["id"], "device_uid": "fixture-device", "device_name": "Fixture",
        "firmware_version": "test-version",
    })
    assert response.status_code == 201
    return response.json()


def heartbeat_payload(device, machine):
    return {"device_uid": device["device_uid"], "serial_number": machine["serial_number"]}


def test_machine_crud_persists(client, admin, db, machine):
    id = machine["id"]
    assert client.get(MACHINES + f"/{id}", headers=admin).json() == machine
    assert client.get(MACHINES, headers=admin).json() == [machine]
    changed = client.patch(MACHINES + f"/{id}", headers=admin,
                           json={"name": "Updated", "description": None, "status": "FAULT"})
    assert changed.status_code == 200
    db.expire_all()
    stored = db.get(Machine, id)
    assert stored.name == "Updated" and stored.description is None and stored.status == "FAULT"
    response = client.delete(MACHINES + f"/{id}", headers=admin)
    assert response.status_code == 204 and response.content == b""
    assert client.get(MACHINES + f"/{id}", headers=admin).status_code == 404


def test_device_crud_and_reassociation(client, admin, db, machine, device):
    id = device["id"]
    assert device["last_seen_at"] is None and device["is_active"]
    assert client.get(DEVICES + f"/{id}", headers=admin).json() == device
    assert client.get(DEVICES, headers=admin).json() == [device]
    other = client.post(MACHINES, json=machine_payload("second"), headers=admin).json()
    changed = client.patch(DEVICES + f"/{id}", headers=admin, json={
        "machine_id": other["id"], "device_name": "Updated", "firmware_version": None,
    })
    assert changed.status_code == 200
    db.expire_all()
    stored = db.get(Device, id)
    assert stored.machine_id == other["id"] and stored.device_name == "Updated"
    assert stored.firmware_version is None
    assert client.delete(DEVICES + f"/{id}", headers=admin).status_code == 204
    assert client.get(DEVICES + f"/{id}", headers=admin).status_code == 404


@pytest.mark.parametrize("path", [MACHINES, DEVICES])
@pytest.mark.parametrize("method", ["get", "patch", "delete"])
def test_nonexistent_record(client, admin, path, method):
    kwargs = {"json": {}} if method == "patch" else {}
    assert client.request(method, path + "/9223372036854775807", headers=admin, **kwargs).status_code == 404


def test_duplicates_and_missing_parent_are_controlled(client, admin, machine, device):
    assert client.post(MACHINES, json=machine_payload(), headers=admin).status_code == 409
    duplicate = {"machine_id": machine["id"], "device_uid": device["device_uid"], "device_name": "Duplicate"}
    assert client.post(DEVICES, json=duplicate, headers=admin).status_code == 409
    absent_parent = duplicate | {"device_uid": "new", "machine_id": 9223372036854775807}
    assert client.post(DEVICES, json=absent_parent, headers=admin).status_code == 404
    assert client.patch(DEVICES + f"/{device['id']}", json={"machine_id": 9223372036854775807}, headers=admin).status_code == 404
    assert client.get(DEVICES + f"/{device['id']}", headers=admin).json()["machine_id"] == machine["id"]
    other = client.post(MACHINES, json=machine_payload("other"), headers=admin).json()
    assert client.patch(MACHINES + f"/{other['id']}", json={"serial_number": machine["serial_number"]}, headers=admin).status_code == 409
    other_device = client.post(DEVICES, json=duplicate | {"device_uid": "other"}, headers=admin).json()
    assert client.patch(DEVICES + f"/{other_device['id']}", json={"device_uid": device["device_uid"]}, headers=admin).status_code == 409
    assert client.get(DEVICES + f"/{other_device['id']}", headers=admin).json()["device_uid"] == "other"


def test_delete_restrict_and_history_after_reassociation(client, admin, db, records):
    machine, _, device, reading, event, _, _ = records
    assert client.delete(MACHINES + f"/{machine.id}", headers=admin).status_code == 409
    assert client.delete(DEVICES + f"/{device.id}", headers=admin).status_code == 409
    other = client.post(MACHINES, json=machine_payload("other"), headers=admin).json()
    assert client.patch(DEVICES + f"/{device.id}", headers=admin, json={"machine_id": other["id"]}).status_code == 200
    db.expire_all()
    assert reading.machine_id == event.machine_id == machine.id
    assert device.machine_id == other["id"]
    assert client.delete(MACHINES + f"/{machine.id}", headers=admin).status_code == 409


def test_machine_referenced_only_by_device_cannot_be_deleted(client, admin, machine, device):
    assert client.delete(MACHINES + f"/{machine['id']}", headers=admin).status_code == 409
    assert client.get(DEVICES + f"/{device['id']}", headers=admin).status_code == 200


@pytest.mark.parametrize("role", ["OPERATOR", "VIEWER"])
def test_rbac_read_allowed_writes_forbidden(client, admin, db, user, machine, device, role):
    user.role = role
    db.commit()
    for path, row, payload in ((MACHINES, machine, machine_payload("denied")),
                               (DEVICES, device, {"machine_id": machine["id"], "device_uid": "denied", "device_name": "Denied"})):
        assert client.get(path, headers=admin).status_code == 200
        assert client.get(path + f"/{row['id']}", headers=admin).status_code == 200
        assert client.post(path, headers=admin, json=payload).status_code == 403
        assert client.patch(path + f"/{row['id']}", headers=admin, json={}).status_code == 403
        assert client.delete(path + f"/{row['id']}", headers=admin).status_code == 403


@pytest.mark.parametrize("path", [MACHINES, DEVICES])
def test_user_authentication_required(client, db, user, settings, admin, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"X-API-Key": KEY}).status_code == 401
    refresh = issue_token(user.id, "refresh", settings)
    assert client.get(path, headers={"Authorization": "Bearer " + refresh}).status_code == 401
    user.is_active = False
    db.commit()
    assert client.get(path, headers=admin).status_code == 401


@pytest.mark.parametrize("field", ["id", "created_at", "updated_at", "last_seen_at"])
def test_internal_fields_rejected(client, admin, machine, device, field):
    if field != "last_seen_at":
        assert client.post(MACHINES, headers=admin, json=machine_payload("new") | {field: 1}).status_code == 422
        assert client.patch(MACHINES + f"/{machine['id']}", headers=admin, json={field: 1}).status_code == 422
    payload = {"machine_id": machine["id"], "device_uid": "new", "device_name": "Test", field: 1}
    assert client.post(DEVICES, headers=admin, json=payload).status_code == 422
    assert client.patch(DEVICES + f"/{device['id']}", headers=admin, json={field: 1}).status_code == 422


def test_invalid_payloads(client, admin, machine, device):
    assert client.post(MACHINES, json=machine_payload() | {"status": "ONLINE"}, headers=admin).status_code == 422
    for field in ("name", "serial_number", "status"):
        assert client.patch(MACHINES + f"/{machine['id']}", json={field: None}, headers=admin).status_code == 422
    for field in ("device_uid", "machine_id", "is_active"):
        assert client.patch(DEVICES + f"/{device['id']}", json={field: None}, headers=admin).status_code == 422
    for id in ("0", "-1", "9223372036854775808", "not-an-id"):
        assert client.get(MACHINES + "/" + id, headers=admin).status_code == 422
        assert client.get(DEVICES + "/" + id, headers=admin).status_code == 422


def test_heartbeat_utc_firmware_no_events_or_status_change(client, admin, db, machine, device):
    before = datetime.now(timezone.utc)
    response = client.post(HEARTBEAT, headers={"X-API-Key": KEY}, json={
        **heartbeat_payload(device, machine), "firmware_version": "new-version",
        "status": "ONLINE", "uptime_seconds": 123,
    })
    after = datetime.now(timezone.utc)
    assert response.status_code == 200
    seen = datetime.fromisoformat(response.json()["last_seen_at"].replace("Z", "+00:00"))
    assert before <= seen <= after
    assert seen.utcoffset().total_seconds() == 0
    db.expire_all()
    assert db.get(Device, device["id"]).last_seen_at == seen
    assert db.get(Device, device["id"]).firmware_version == "new-version"
    assert db.get(Machine, machine["id"]).status == "MAINTENANCE"
    again = client.post(HEARTBEAT, headers={"X-API-Key": KEY}, json=heartbeat_payload(device, machine))
    assert again.status_code == 200 and again.json()["firmware_version"] == "new-version"
    assert datetime.fromisoformat(again.json()["last_seen_at"].replace("Z", "+00:00")) >= seen
    assert db.scalar(select(func.count()).select_from(Event)) == 0
    assert db.scalar(select(func.count()).select_from(SensorReading)) == 0


def test_heartbeat_not_found_mismatch_and_inactive(client, admin, db, machine, device):
    payload = heartbeat_payload(device, machine)
    key = {"X-API-Key": KEY}
    assert client.post(HEARTBEAT, json=payload | {"device_uid": "absent"}, headers=key).status_code == 404
    assert client.post(HEARTBEAT, json=payload | {"serial_number": "absent"}, headers=key).status_code == 404
    other = client.post(MACHINES, json=machine_payload("other"), headers=admin).json()
    assert client.post(HEARTBEAT, json=payload | {"serial_number": other["serial_number"]}, headers=key).status_code == 409
    assert client.patch(DEVICES + f"/{device['id']}", json={"is_active": False}, headers=admin).status_code == 200
    assert client.post(HEARTBEAT, json=payload, headers=key).status_code == 403
    db.expire_all()
    assert db.get(Device, device["id"]).last_seen_at is None
    assert db.scalar(select(func.count()).select_from(Device)) == 1
    assert db.scalar(select(func.count()).select_from(Machine)) == 2


def test_heartbeat_uses_new_association(client, admin, machine, device):
    other = client.post(MACHINES, json=machine_payload("other"), headers=admin).json()
    assert client.patch(DEVICES + f"/{device['id']}", json={"machine_id": other["id"]}, headers=admin).status_code == 200
    assert client.post(HEARTBEAT, json=heartbeat_payload(device, machine), headers={"X-API-Key": KEY}).status_code == 409
    assert client.post(HEARTBEAT, json=heartbeat_payload(device, other), headers={"X-API-Key": KEY}).status_code == 200


@pytest.mark.parametrize("extra", [{"status": "OFFLINE"}, {"uptime_seconds": -1},
    {"uptime_seconds": 1.5}, {"firmware_version": None}, {"last_seen_at": "2020-01-01T00:00:00Z"},
    {"device_id": 1}, {"machine_id": 1}, {"status": None}])
def test_invalid_heartbeat_no_side_effects(client, db, machine, device, extra):
    response = client.post(HEARTBEAT, json=heartbeat_payload(device, machine) | extra, headers={"X-API-Key": KEY})
    assert response.status_code == 422
    assert db.get(Device, device["id"]).last_seen_at is None


def test_heartbeat_authentication(client, admin, db, machine, device, monkeypatch, caplog):
    payload = heartbeat_payload(device, machine)
    for headers in ({}, admin, {"X-API-Key": "wrong"}):
        response = client.post(HEARTBEAT, json=payload, headers=headers)
        assert response.status_code == 401 and KEY not in response.text
    monkeypatch.delenv("DEVICE_API_KEY")
    assert client.post(HEARTBEAT, json=payload, headers={"X-API-Key": KEY}).status_code == 503
    assert db.get(Device, device["id"]).last_seen_at is None
    assert KEY not in caplog.text


def test_openapi_contracts():
    schema = app.openapi()
    for path in (MACHINES, DEVICES):
        assert set(schema["paths"][path]) == {"get", "post"}
        assert set(schema["paths"][path + "/{id}"]) == {"get", "patch", "delete"}
        assert schema["paths"][path]["get"]["security"] == [{"HTTPBearer": []}]
    assert schema["paths"][HEARTBEAT]["post"]["security"] == [{"APIKeyHeader": []}]
    assert schema["components"]["securitySchemes"]["APIKeyHeader"]["name"] == "X-API-Key"
    models = schema["components"]["schemas"]
    for name in ("MachineCreate", "MachineUpdate", "DeviceCreate", "DeviceUpdate", "DeviceHeartbeatRequest"):
        assert not {"id", "created_at", "updated_at", "last_seen_at"} & set(models[name]["properties"])

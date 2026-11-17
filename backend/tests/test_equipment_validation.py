"""NUL rejection through real routers and transactional PostgreSQL fixtures."""

import pytest
from sqlalchemy import func, select

from app.models import Device, Machine
from test_auth import settings, user
from test_domain import db
from test_equipment import (
    DEVICES, HEARTBEAT, KEY, MACHINES, admin, client, device, heartbeat_payload,
    machine, machine_payload,
)

MACHINE_TEXT = ("serial_number", "name", "block", "corridor", "description")
DEVICE_TEXT = ("device_uid", "device_name", "firmware_version")
VALID_TEXT = "  Atenção — máquina 🔔\nSegunda linha\t  "


def assert_nul_error(response, field):
    assert response.status_code == 422
    errors = response.json()["detail"]
    assert any(error["loc"] == ["body", field] for error in errors)


@pytest.mark.parametrize("field", MACHINE_TEXT)
@pytest.mark.parametrize("method", ["post", "patch"])
def test_machine_nul_no_write_then_valid(client, admin, db, machine, field, method):
    path = MACHINES if method == "post" else f"{MACHINES}/{machine['id']}"
    payload = machine_payload("new-fixture-machine") if method == "post" else {}
    request = getattr(client, method)
    response = request(path, headers=admin, json=payload | {field: "before\x00after"})
    assert_nul_error(response, field)
    assert db.scalar(select(func.count()).select_from(Machine)) == 1
    assert client.get(f"{MACHINES}/{machine['id']}", headers=admin).json() == machine
    valid = request(path, headers=admin, json=payload | {field: VALID_TEXT})
    assert valid.status_code == (201 if method == "post" else 200)
    assert valid.json()[field] == VALID_TEXT
    db.expire_all()
    assert getattr(db.get(Machine, valid.json()["id"]), field) == VALID_TEXT


@pytest.mark.parametrize("field", DEVICE_TEXT)
@pytest.mark.parametrize("method", ["post", "patch"])
def test_device_nul_no_write_then_valid(client, admin, db, machine, device, field, method):
    path = DEVICES if method == "post" else f"{DEVICES}/{device['id']}"
    payload = {"machine_id": machine["id"], "device_uid": "new-fixture-device",
               "device_name": "Fixture"} if method == "post" else {}
    request = getattr(client, method)
    response = request(path, headers=admin, json=payload | {field: "before\x00after"})
    assert_nul_error(response, field)
    assert db.scalar(select(func.count()).select_from(Device)) == 1
    assert client.get(f"{DEVICES}/{device['id']}", headers=admin).json() == device
    valid = request(path, headers=admin, json=payload | {field: VALID_TEXT})
    assert valid.status_code == (201 if method == "post" else 200)
    assert valid.json()[field] == VALID_TEXT
    db.expire_all()
    assert getattr(db.get(Device, valid.json()["id"]), field) == VALID_TEXT


@pytest.mark.parametrize("field", ["device_uid", "serial_number", "firmware_version"])
def test_heartbeat_nul_preserves_device_then_valid(client, admin, db, machine, device, field):
    payload = heartbeat_payload(device, machine) | {"firmware_version": VALID_TEXT}
    response = client.post(HEARTBEAT, headers={"X-API-Key": KEY},
                           json=payload | {field: "before\x00after"})
    assert_nul_error(response, field)
    assert client.get(f"{DEVICES}/{device['id']}", headers=admin).json() == device
    db.expire_all()
    assert db.get(Device, device["id"]).last_seen_at is None
    valid = client.post(HEARTBEAT, headers={"X-API-Key": KEY}, json=payload)
    assert valid.status_code == 200
    assert valid.json()["firmware_version"] == VALID_TEXT
    assert valid.json()["last_seen_at"] is not None


def test_heartbeat_accepts_exact_unicode_identifiers(client, admin, machine, device):
    changed_machine = client.patch(f"{MACHINES}/{machine['id']}", headers=admin,
                                   json={"serial_number": VALID_TEXT})
    changed_device = client.patch(f"{DEVICES}/{device['id']}", headers=admin,
                                  json={"device_uid": VALID_TEXT})
    assert changed_machine.status_code == changed_device.status_code == 200
    response = client.post(HEARTBEAT, headers={"X-API-Key": KEY},
                           json=heartbeat_payload(changed_device.json(), changed_machine.json()))
    assert response.status_code == 200
    assert response.json()["device_uid"] == VALID_TEXT


def test_nullable_and_omitted_fields_keep_existing_contract(client, admin, machine, device):
    machine_path = f"{MACHINES}/{machine['id']}"
    device_path = f"{DEVICES}/{device['id']}"
    for path, field in ((machine_path, "description"), (device_path, "firmware_version")):
        assert client.patch(path, headers=admin, json={field: None}).status_code == 200
        unchanged = client.patch(path, headers=admin, json={})
        assert unchanged.status_code == 200 and unchanged.json()[field] is None
    payload = heartbeat_payload(device, machine)
    assert client.post(HEARTBEAT, headers={"X-API-Key": KEY},
                       json=payload | {"firmware_version": None}).status_code == 422
    assert client.post(HEARTBEAT, headers={"X-API-Key": KEY}, json=payload).status_code == 200

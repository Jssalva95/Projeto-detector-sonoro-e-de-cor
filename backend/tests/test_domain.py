"""Approved contracts, tested in a transactional schema removed by rollback."""

import importlib.util
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.session import database_url
from app.models import Alert, AlertRecipient, Device, Event, Machine, SensorReading, User
from app.schemas.domain import (
    AlertRead, AlertRecipientRead, DeviceRead, EventCreate, EventRead,
    MachineRead, SensorReadingCreate, SensorReadingRead, UserRead,
)


def domain_migration():
    path = Path("alembic/versions/0002_domain_models_approved_domain.py")
    spec = importlib.util.spec_from_file_location("domain_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def db():
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("Requires PostgreSQL")
    engine = create_engine(database_url(), hide_parameters=True)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                # UUID-generated identifier only; no user input or production rows.
                schema = "test_domain_" + uuid4().hex
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                with Operations.context(MigrationContext.configure(connection)):
                    domain_migration().upgrade()
                with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                    yield session
            finally:
                transaction.rollback()  # Removes tables, rows, sequences and schema.
    finally:
        engine.dispose()


@pytest.fixture
def records(db):
    now = datetime.now(timezone.utc)
    machine = Machine(serial_number="fixture", name="Fixture", block="Test",
                      corridor="Test", status="NORMAL")
    user = User(name="Fixture", email="Fixture@example.invalid",
                password_hash="test-only", role="VIEWER")
    device = Device(machine=machine, device_uid="fixture", device_name="Fixture")
    reading = SensorReading(
        uuid=uuid4(), machine=machine, device=device, timestamp=now, color="BLUE",
        red_value=812, green_value=190, blue_value=221, color_confidence=0.8,
        sound_detected=True, sound_amplitude=612, sound_duration_ms=0,
    )
    event = Event(uuid=uuid4(), machine=machine, device=device,
                  event_type="DEVICE_ONLINE", severity="INFO", started_at=now,
                  message="Test only", sound_amplitude=4095)
    recipient = AlertRecipient(name="Fixture", channel="EMAIL",
                               destination="fixture@example.invalid")
    attempt = Alert(event=event, recipient=recipient, channel="EMAIL", status="PENDING")
    db.add_all([machine, user, device, reading, event, recipient, attempt])
    db.commit()
    return machine, user, device, reading, event, recipient, attempt


def test_roundtrip_all_models_and_schemas(db, records):
    schemas = (MachineRead, UserRead, DeviceRead, SensorReadingRead,
               EventRead, AlertRecipientRead, AlertRead)
    db.expire_all()
    for row, schema in zip(records, schemas):
        data = schema.model_validate(row)
        assert data.id > 0
        assert data.created_at.utcoffset() == timedelta(0)
    assert "password_hash" not in UserRead.model_validate(records[1]).model_dump()
    assert records[3].sound_amplitude == 612
    assert records[4].sound_amplitude == 4095
    assert records[3].red_value > 255
    assert records[2].firmware_version is None
    assert records[3].sound_trigger is None
    assert records[4].color is None


def test_reassociation_preserves_history_and_retries(db, records):
    original, _, device, reading, event, recipient, first = records
    other = Machine(serial_number="other", name="Other", block="Test",
                    corridor="Test", status="MAINTENANCE")
    device.machine = other
    second = Alert(event=event, recipient=recipient, channel="EMAIL", status="FAILED")
    db.add(second)
    db.commit()
    db.expire_all()
    assert device.machine_id == other.id != original.id
    assert reading.machine_id == event.machine_id == original.id
    assert reading.device is device and event.device is device
    assert {attempt.id for attempt in event.alerts} == {first.id, second.id}


@pytest.mark.parametrize("kind", ["email", "serial", "device", "reading_uuid", "event_uuid"])
def test_unique_constraints(db, records, kind):
    machine, user, device, reading, event, _, _ = records
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            if kind == "email":
                db.add(User(name="Duplicate", email=user.email.lower(),
                            password_hash="test-only", role="VIEWER"))
            elif kind == "serial":
                db.add(Machine(serial_number=machine.serial_number, name="Duplicate",
                               block="Test", corridor="Test", status="NORMAL"))
            elif kind == "device":
                db.add(Device(machine=machine, device_uid=device.device_uid, device_name="Duplicate"))
            elif kind == "reading_uuid":
                values = SensorReadingRead.model_validate(reading).model_dump(
                    exclude={"id", "created_at"},
                )
                db.add(SensorReading(**values))
            else:
                values = EventRead.model_validate(event).model_dump(exclude={"id", "created_at"})
                db.add(Event(**values))
            db.flush()


@pytest.mark.parametrize("index,field,value", [
    (0, "status", "INVALID"), (1, "role", "INVALID"),
    (3, "color_confidence", 1.1), (3, "red_value", -1),
    (3, "sound_duration_ms", -1), (3, "color", "GREEN"),
    (4, "acknowledged", True), (4, "severity", "INVALID"),
    (4, "event_type", "INVALID"), (4, "sound_duration_ms", -1),
    (5, "channel", "INVALID"), (6, "status", "INVALID"),
    (6, "channel", "INVALID"), (2, "machine_id", -1),
])
def test_database_checks_and_foreign_key(db, records, index, field, value):
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            setattr(records[index], field, value)
            db.flush()


def test_acknowledgment_and_time_order(db, records):
    _, user, _, _, event, _, _ = records
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            event.ended_at = event.started_at - timedelta(seconds=1)
            db.flush()
    with db.no_autoflush:
        event.acknowledged = True
        event.acknowledged_user = user
        event.acknowledged_at = event.started_at
    db.commit()
    assert event in user.acknowledged_events
    assert EventRead.model_validate(event).acknowledged_by == user.id


def test_restrict_delete_and_primary_key_update(db, records):
    machine = records[0]
    assert machine.devices  # Loaded children must not be deleted or set to NULL.
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.delete(machine)
            db.flush()
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.execute(update(Machine).where(Machine.id == machine.id).values(id=999999))


def test_schema_utc_and_raw_amplitude():
    values = dict(
        uuid=uuid4(), machine_id=1, device_id=1, timestamp="2026-10-20T08:00:00-04:00",
        color="UNKNOWN", red_value=812, green_value=190, blue_value=221,
        color_confidence=1, sound_detected=True, sound_amplitude=4095, sound_duration_ms=0,
    )
    reading = SensorReadingCreate(**values)
    assert reading.timestamp.hour == 12
    assert reading.timestamp.utcoffset() == timedelta(0)
    assert reading.sound_amplitude == 4095
    for override in ({"timestamp": "2026-10-20T08:00:00"}, {"color_confidence": 1.01},
                     {"color": "GREEN"}, {"sound_duration_ms": -1}):
        with pytest.raises(ValidationError):
            SensorReadingCreate(**(values | override))
    event = dict(uuid=uuid4(), machine_id=1, device_id=1, event_type="DEVICE_OFFLINE",
                 severity="INFO", started_at=reading.timestamp, message="Test")
    assert EventCreate(**event).color is None
    for override in ({"acknowledged": True}, {"acknowledged_by": 1},
                     {"ended_at": reading.timestamp - timedelta(seconds=1)}):
        with pytest.raises(ValidationError):
            EventCreate(**(event | override))


def test_migration_structure_and_downgrade_in_isolated_schema(db):
    connection = db.connection()
    inspector = inspect(connection)
    expected = {"users", "machines", "devices", "sensor_readings", "events",
                "alert_recipients", "alerts"}
    assert set(inspector.get_table_names()) == expected
    for table in expected:
        assert inspector.get_pk_constraint(table)["constrained_columns"] == ["id"]
        columns = {column["name"]: column for column in inspector.get_columns(table)}
        assert str(columns["id"]["type"]) == "BIGINT"
        assert columns["id"]["identity"] is not None
        assert columns["created_at"]["type"].timezone
        for fk in inspector.get_foreign_keys(table):
            assert fk["options"]["ondelete"] == fk["options"]["onupdate"] == "RESTRICT"
    for table in ("events", "sensor_readings"):
        checks = inspector.get_check_constraints(table)
        assert all("sound_amplitude" not in check["sqltext"] for check in checks)
    with Operations.context(MigrationContext.configure(connection)):
        domain_migration().downgrade()
    assert inspect(connection).get_table_names() == []

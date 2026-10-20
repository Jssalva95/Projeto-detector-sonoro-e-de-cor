"""Approved phase 1 data mappings. No ingestion, authentication or sending logic."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, Double, ForeignKey,
    Identity, Index, Integer, Text, UniqueConstraint, Uuid, func, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import AlertStatus, Channel, Color, EventType, MachineStatus, Role, Severity


def enum_check(column: str, values: type[StrEnum], name: str) -> CheckConstraint:
    literals = ", ".join(repr(value.value) for value in values)
    return CheckConstraint(f"{column} IN ({literals})", name=name)


def reference(target: str) -> ForeignKey:
    return ForeignKey(target, ondelete="RESTRICT", onupdate="RESTRICT")


class IdentityCreated:
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Updated:
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )


class User(IdentityCreated, Updated, Base):
    __tablename__ = "users"
    __table_args__ = (enum_check("role", Role, "ck_users_role"),)

    name: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    acknowledged_events: Mapped[list["Event"]] = relationship(
        back_populates="acknowledged_user", passive_deletes="all",
    )


Index("uq_users_email_lower", func.lower(User.email), unique=True)


class Machine(IdentityCreated, Updated, Base):
    __tablename__ = "machines"
    __table_args__ = (
        UniqueConstraint("serial_number", name="uq_machines_serial_number"),
        enum_check("status", MachineStatus, "ck_machines_status"),
    )

    serial_number: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    block: Mapped[str] = mapped_column(Text)
    corridor: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    devices: Mapped[list["Device"]] = relationship(back_populates="machine", passive_deletes="all")
    readings: Mapped[list["SensorReading"]] = relationship(back_populates="machine", passive_deletes="all")
    events: Mapped[list["Event"]] = relationship(back_populates="machine", passive_deletes="all")


class Device(IdentityCreated, Updated, Base):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("device_uid", name="uq_devices_device_uid"),)

    machine_id: Mapped[int] = mapped_column(BigInteger, reference("machines.id"), index=True)
    device_uid: Mapped[str] = mapped_column(Text)
    device_name: Mapped[str] = mapped_column(Text)
    firmware_version: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    machine: Mapped[Machine] = relationship(back_populates="devices")
    readings: Mapped[list["SensorReading"]] = relationship(back_populates="device", passive_deletes="all")
    events: Mapped[list["Event"]] = relationship(back_populates="device", passive_deletes="all")


class SensorReading(IdentityCreated, Base):
    __tablename__ = "sensor_readings"
    __table_args__ = (
        UniqueConstraint("uuid", name="uq_sensor_readings_uuid"),
        enum_check("color", Color, "ck_sensor_readings_color"),
        CheckConstraint("color_confidence >= 0 AND color_confidence <= 1", name="ck_sensor_readings_confidence"),
        CheckConstraint("red_value >= 0 AND green_value >= 0 AND blue_value >= 0", name="ck_sensor_readings_rgb"),
        CheckConstraint("sound_duration_ms >= 0", name="ck_sensor_readings_duration"),
    )

    uuid: Mapped[UUID] = mapped_column(Uuid)
    machine_id: Mapped[int] = mapped_column(BigInteger, reference("machines.id"), index=True)
    device_id: Mapped[int] = mapped_column(BigInteger, reference("devices.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    color: Mapped[str] = mapped_column(Text)
    red_value: Mapped[int] = mapped_column(Integer)
    green_value: Mapped[int] = mapped_column(Integer)
    blue_value: Mapped[int] = mapped_column(Integer)
    color_confidence: Mapped[float] = mapped_column(Double)
    sound_detected: Mapped[bool] = mapped_column(Boolean)
    sound_amplitude: Mapped[float] = mapped_column(Double)
    sound_trigger: Mapped[bool | None] = mapped_column(Boolean)
    sound_duration_ms: Mapped[int] = mapped_column(BigInteger)
    machine: Mapped[Machine] = relationship(back_populates="readings")
    device: Mapped[Device] = relationship(back_populates="readings")


class Event(IdentityCreated, Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("uuid", name="uq_events_uuid"),
        enum_check("event_type", EventType, "ck_events_type"),
        enum_check("severity", Severity, "ck_events_severity"),
        enum_check("color", Color, "ck_events_color"),
        CheckConstraint("sound_duration_ms >= 0", name="ck_events_duration"),
        CheckConstraint("ended_at >= started_at", name="ck_events_time_order"),
        CheckConstraint(
            "(NOT acknowledged AND acknowledged_by IS NULL AND acknowledged_at IS NULL) OR "
            "(acknowledged AND acknowledged_by IS NOT NULL AND acknowledged_at IS NOT NULL)",
            name="ck_events_acknowledgment",
        ),
    )

    uuid: Mapped[UUID] = mapped_column(Uuid)
    machine_id: Mapped[int] = mapped_column(BigInteger, reference("machines.id"), index=True)
    device_id: Mapped[int] = mapped_column(BigInteger, reference("devices.id"), index=True)
    event_type: Mapped[str] = mapped_column(Text, index=True)
    severity: Mapped[str] = mapped_column(Text, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    color: Mapped[str | None] = mapped_column(Text)
    sound_detected: Mapped[bool | None] = mapped_column(Boolean)
    sound_amplitude: Mapped[float | None] = mapped_column(Double)
    sound_duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    message: Mapped[str] = mapped_column(Text)
    acknowledged: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    acknowledged_by: Mapped[int | None] = mapped_column(BigInteger, reference("users.id"), index=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    machine: Mapped[Machine] = relationship(back_populates="events")
    device: Mapped[Device] = relationship(back_populates="events")
    acknowledged_user: Mapped[User | None] = relationship(back_populates="acknowledged_events")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="event", passive_deletes="all")


class AlertRecipient(IdentityCreated, Updated, Base):
    __tablename__ = "alert_recipients"
    __table_args__ = (enum_check("channel", Channel, "ck_alert_recipients_channel"),)

    name: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(Text)
    destination: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    alerts: Mapped[list["Alert"]] = relationship(back_populates="recipient", passive_deletes="all")


class Alert(IdentityCreated, Base):
    __tablename__ = "alerts"
    __table_args__ = (
        enum_check("channel", Channel, "ck_alerts_channel"),
        enum_check("status", AlertStatus, "ck_alerts_status"),
    )

    event_id: Mapped[int] = mapped_column(BigInteger, reference("events.id"), index=True)
    recipient_id: Mapped[int] = mapped_column(BigInteger, reference("alert_recipients.id"), index=True)
    channel: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    event: Mapped[Event] = relationship(back_populates="alerts")
    recipient: Mapped[AlertRecipient] = relationship(back_populates="alerts")

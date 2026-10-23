"""Data contracts only; no HTTP endpoints or domain workflows."""

from datetime import timezone
from typing import Annotated, Self
from uuid import UUID

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.models.enums import AlertStatus, Channel, Color, EventType, MachineStatus, Role, Severity

UtcDateTime = Annotated[AwareDatetime, AfterValidator(lambda value: value.astimezone(timezone.utc))]
Identifier = Annotated[int, Field(gt=0, le=9223372036854775807)]
Duration = Annotated[int, Field(ge=0, le=9223372036854775807)]
RgbValue = Annotated[int, Field(ge=0, le=2147483647)]


class DataSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class Created(DataSchema):
    id: Identifier
    created_at: UtcDateTime


class Updated(DataSchema):
    updated_at: UtcDateTime


class UserData(DataSchema):
    name: str
    email: str
    role: Role
    is_active: bool = True


class UserCreate(UserData):
    password_hash: str = Field(repr=False)


class UserRead(UserData, Created, Updated):
    """Public representation deliberately excludes password_hash."""


class MachineCreate(DataSchema):
    serial_number: str
    name: str
    block: str
    corridor: str
    description: str | None = None
    status: MachineStatus


class MachineRead(MachineCreate, Created, Updated):
    pass


class DeviceCreate(DataSchema):
    machine_id: Identifier
    device_uid: str
    device_name: str
    firmware_version: str | None = None
    is_active: bool = True


class DeviceRead(DeviceCreate, Created, Updated):
    last_seen_at: UtcDateTime | None = None


class SensorReadingCreate(DataSchema):
    uuid: UUID
    machine_id: Identifier
    device_id: Identifier
    timestamp: UtcDateTime
    color: Color
    red_value: RgbValue
    green_value: RgbValue
    blue_value: RgbValue
    color_confidence: Annotated[float, Field(ge=0, le=1)]
    sound_detected: bool
    sound_amplitude: Annotated[float, Field(allow_inf_nan=False)]
    sound_trigger: bool | None = None
    sound_duration_ms: Duration


class SensorReadingRead(SensorReadingCreate, Created):
    pass


class EventCreate(DataSchema):
    uuid: UUID
    machine_id: Identifier
    device_id: Identifier
    event_type: EventType
    severity: Severity
    started_at: UtcDateTime
    ended_at: UtcDateTime | None = None
    color: Color | None = None
    sound_detected: bool | None = None
    sound_amplitude: float | None = None
    sound_duration_ms: Duration | None = None
    message: str
    acknowledged: bool = False
    acknowledged_by: Identifier | None = None
    acknowledged_at: UtcDateTime | None = None

    @model_validator(mode="after")
    def validate_consistency(self) -> Self:
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at must not precede started_at")
        if self.acknowledged:
            if self.acknowledged_by is None or self.acknowledged_at is None:
                raise ValueError("Acknowledged events require user and timestamp")
        elif self.acknowledged_by is not None or self.acknowledged_at is not None:
            raise ValueError("Unacknowledged events must not have acknowledgment metadata")
        return self


class EventRead(EventCreate, Created):
    pass


class AlertRecipientCreate(DataSchema):
    name: str
    channel: Channel
    destination: str
    is_active: bool = True


class AlertRecipientRead(AlertRecipientCreate, Created, Updated):
    pass


class AlertCreate(DataSchema):
    event_id: Identifier
    recipient_id: Identifier
    channel: Channel
    status: AlertStatus
    sent_at: UtcDateTime | None = None
    error_message: str | None = None


class AlertRead(AlertCreate, Created):
    pass

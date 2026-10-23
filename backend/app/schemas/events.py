"""Public event input excludes server-owned acknowledgment metadata."""

from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.models.enums import Color, EventType, Severity
from app.schemas.domain import DataSchema, Duration, Identifier, UtcDateTime


class EventRequest(DataSchema):
    uuid: UUID
    machine_id: Identifier
    device_id: Identifier
    event_type: EventType
    severity: Severity
    started_at: UtcDateTime
    ended_at: UtcDateTime | None = None
    color: Color | None = None
    sound_detected: bool | None = None
    sound_amplitude: Annotated[float, Field(allow_inf_nan=False)] | None = None
    sound_duration_ms: Duration | None = None
    message: str

    @field_validator("message")
    @classmethod
    def reject_nul(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("Message must not contain NUL characters")
        return value

    @model_validator(mode="after")
    def ordered_times(self) -> Self:
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at must not precede started_at")
        return self


class EventFilters(DataSchema):
    machine_id: Identifier | None = None
    event_type: EventType | None = None
    severity: Severity | None = None
    acknowledged: bool | None = None
    start_date: UtcDateTime | None = None
    end_date: UtcDateTime | None = None
    limit: Annotated[int, Field(ge=1, le=200)] = 50
    offset: Annotated[int, Field(ge=0, le=9223372036854775807)] = 0

    @model_validator(mode="after")
    def ordered_dates(self) -> Self:
        if self.start_date is not None and self.end_date is not None:
            if self.start_date > self.end_date:
                raise ValueError("start_date must not exceed end_date")
        return self

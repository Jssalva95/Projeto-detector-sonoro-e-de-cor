"""Phase 3 partial updates and the approved device heartbeat contract."""

from typing import Annotated, ClassVar, Literal, Self

from pydantic import Field, model_validator

from app.models.enums import MachineStatus
from app.schemas.domain import DataSchema, Identifier, NulFreeText


class PartialUpdate(DataSchema):
    nullable_fields: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def reject_explicit_null(self) -> Self:
        for name in self.model_fields_set - self.nullable_fields:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class MachineUpdate(PartialUpdate):
    nullable_fields = frozenset({"description"})
    serial_number: NulFreeText | None = None
    name: NulFreeText | None = None
    block: NulFreeText | None = None
    corridor: NulFreeText | None = None
    description: NulFreeText | None = None
    status: MachineStatus | None = None


class DeviceUpdate(PartialUpdate):
    nullable_fields = frozenset({"firmware_version"})
    machine_id: Identifier | None = None
    device_uid: NulFreeText | None = None
    device_name: NulFreeText | None = None
    firmware_version: NulFreeText | None = None
    is_active: bool | None = None


class DeviceHeartbeatRequest(PartialUpdate):
    device_uid: NulFreeText
    serial_number: NulFreeText
    firmware_version: NulFreeText | None = None
    status: Literal["ONLINE"] | None = None
    uptime_seconds: Annotated[int, Field(ge=0, strict=True)] | None = None

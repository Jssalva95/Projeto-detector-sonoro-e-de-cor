"""Approved operational read model; no additions to existing HTTP payloads."""

from enum import StrEnum
from typing import Literal
from uuid import UUID

from app.models.enums import MachineStatus
from app.schemas.domain import DataSchema, Identifier, UtcDateTime


class Availability(StrEnum):
    ONLINE = 'ONLINE'
    OFFLINE = 'OFFLINE'
    UNKNOWN = 'UNKNOWN'


class StatusReason(StrEnum):
    REGISTERED_MAINTENANCE = 'REGISTERED_MAINTENANCE'
    ACTIVE_FAULT = 'ACTIVE_FAULT'
    ALL_ACTIVE_DEVICES_OFFLINE = 'ALL_ACTIVE_DEVICES_OFFLINE'
    RECOVERED_AND_ONLINE = 'RECOVERED_AND_ONLINE'
    INSUFFICIENT_EVIDENCE = 'INSUFFICIENT_EVIDENCE'


class EventEvidence(DataSchema):
    event_id: Identifier
    uuid: UUID
    event_type: Literal['FAULT_CONFIRMED', 'FAULT_RECOVERED', 'DEVICE_ONLINE', 'DEVICE_OFFLINE']
    started_at: UtcDateTime
    created_at: UtcDateTime


class DeviceEvidence(DataSchema):
    device_id: Identifier
    availability: Availability
    last_seen_at: UtcDateTime | None
    connection_event: EventEvidence | None


class OperationalMachine(DataSchema):
    machine_id: Identifier
    name: str
    serial_number: str
    block: str
    corridor: str
    registered_status: MachineStatus
    operational_status: MachineStatus | None
    reason: StatusReason
    fault_active: bool | None
    availability: Availability
    fault_evidence: EventEvidence | None
    device_evidence: list[DeviceEvidence]

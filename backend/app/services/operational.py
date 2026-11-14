"""Last known state only; never mutate machines, events, heartbeats or alert queues."""

from collections.abc import Sequence

from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from app.models.enums import MachineStatus
from app.repositories import operational as repository
from app.schemas.operational import (
    Availability, DeviceEvidence, EventEvidence, OperationalMachine, StatusReason,
)


def availability(devices: Sequence[DeviceEvidence]) -> Availability:
    if any(device.availability == Availability.ONLINE for device in devices):
        return Availability.ONLINE
    if devices and all(device.availability == Availability.OFFLINE for device in devices):
        return Availability.OFFLINE
    return Availability.UNKNOWN


def evaluate(registered: MachineStatus, fault: bool | None,
             connection: Availability) -> tuple[MachineStatus | None, StatusReason]:
    if registered == MachineStatus.MAINTENANCE:
        return MachineStatus.MAINTENANCE, StatusReason.REGISTERED_MAINTENANCE
    if fault is True:
        return MachineStatus.FAULT, StatusReason.ACTIVE_FAULT
    if connection == Availability.OFFLINE:
        return MachineStatus.OFFLINE, StatusReason.ALL_ACTIVE_DEVICES_OFFLINE
    if fault is False and connection == Availability.ONLINE:
        return MachineStatus.NORMAL, StatusReason.RECOVERED_AND_ONLINE
    return None, StatusReason.INSUFFICIENT_EVIDENCE


def event_evidence(row: RowMapping, prefix: str) -> EventEvidence | None:
    if row[prefix + '_id'] is None:
        return None
    return EventEvidence(event_id=row[prefix + '_id'], uuid=row[prefix + '_uuid'],
                         event_type=row[prefix + '_event_type'],
                         started_at=row[prefix + '_started_at'], created_at=row[prefix + '_created_at'])


def list_states(session: Session, machine_id: int | None = None) -> list[OperationalMachine]:
    return states_from_rows(repository.evidence_rows(session, machine_id))


def states_from_rows(rows: Sequence[RowMapping]) -> list[OperationalMachine]:
    """Build the same read model for internal queries and paginated dashboard rows."""
    machines: dict[int, OperationalMachine] = {}
    for row in rows:
        identifier = row['machine_id']
        if identifier not in machines:
            fault = event_evidence(row, 'fault')
            machines[identifier] = OperationalMachine(
                machine_id=identifier, name=row['name'], serial_number=row['serial_number'],
                block=row['block'], corridor=row['corridor'], registered_status=row['registered_status'],
                operational_status=None, reason=StatusReason.INSUFFICIENT_EVIDENCE,
                fault_active=None if fault is None else fault.event_type == 'FAULT_CONFIRMED',
                availability=Availability.UNKNOWN, fault_evidence=fault, device_evidence=[],
            )
        if row['device_id'] is not None:
            connection = event_evidence(row, 'connection')
            state = (Availability.UNKNOWN if connection is None else
                     Availability.ONLINE if connection.event_type == 'DEVICE_ONLINE' else Availability.OFFLINE)
            machines[identifier].device_evidence.append(DeviceEvidence(
                device_id=row['device_id'], availability=state,
                last_seen_at=row['last_seen_at'], connection_event=connection,
            ))
    for machine in machines.values():
        machine.availability = availability(machine.device_evidence)
        machine.operational_status, machine.reason = evaluate(
            machine.registered_status, machine.fault_active, machine.availability,
        )
    return list(machines.values())

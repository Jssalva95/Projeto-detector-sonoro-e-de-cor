"""Stage immutable event snapshots within the HTTP transaction boundary."""

from sqlalchemy.orm import Session

from app.models import Event
from app.websocket.schemas import EventNotification

PENDING_NOTIFICATIONS = 'websocket_pending_notifications'
CRITICAL_TYPES = frozenset({'FAULT_CONFIRMED', 'FAULT_RECOVERED', 'DEVICE_OFFLINE', 'DEVICE_ONLINE'})


def stage_notification(session: Session, event: Event) -> None:
    # Called only for a newly inserted event after the ingestion savepoint exits.
    if event.event_type in CRITICAL_TYPES:
        notification = EventNotification(type=event.event_type, event_id=event.id,
                                         uuid=event.uuid, machine_id=event.machine_id,
                                         timestamp=event.started_at, severity=event.severity)
        session.info.setdefault(PENDING_NOTIFICATIONS, []).append(notification)

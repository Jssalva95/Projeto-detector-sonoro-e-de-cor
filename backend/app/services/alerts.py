"""Queue once per fault cycle, within the caller's locked transaction."""

from sqlalchemy.orm import Session

from app.alerts.config import queue_settings
from app.models import Event
from app.repositories import alerts as repository


def enqueue(session: Session, event: Event, previous_transition: str | None) -> None:
    """Caller must hold the machine lock from before event insertion until commit."""
    if event.event_type != 'FAULT_CONFIRMED' or previous_transition == 'FAULT_CONFIRMED':
        return
    channels, cooldown = queue_settings()
    if not channels:
        return
    recipients = repository.active_recipients(session, channels)
    now = repository.database_now(session)
    for recipient in recipients:
        if not recipient.is_active or recipient.channel not in channels:
            continue
        if not repository.in_cooldown(session, event.machine_id, recipient, now, cooldown):
            repository.insert_pending(session, event, recipient, now)
    session.flush()

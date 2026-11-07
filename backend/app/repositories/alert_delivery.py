"""Durable claims, finalized independently of the external transport."""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.message import render_message
from app.models import Alert, AlertRecipient, Event, Machine
from app.repositories.alerts import database_now


@dataclass(frozen=True)
class Delivery:
    identifier: int
    started_at: datetime
    channel: str
    destination: str = field(repr=False)
    message: str = field(repr=False)


def reserve(session: Session, channels: tuple[str, ...]) -> tuple[bool, Delivery | None]:
    """Caller must commit before returning this delivery to the transport."""
    if not channels:
        return False, None
    row = session.scalar(select(Alert).where(
        Alert.status == 'PENDING', Alert.attempt_started_at.is_(None),
        Alert.channel.in_(channels),
    ).order_by(Alert.id).limit(1).with_for_update(skip_locked=True))
    if row is None:
        return False, None
    row.attempt_started_at = database_now(session)
    recipient = session.get(AlertRecipient, row.recipient_id)
    event = session.get(Event, row.event_id)
    error = None
    if recipient is None or not recipient.is_active:
        error = 'recipient_inactive'
    elif recipient.channel != row.channel:
        error = 'recipient_channel_changed'
    elif event is None or event.event_type != 'FAULT_CONFIRMED':
        error = 'invalid_alert_event'
    if error:
        row.status, row.error_message = 'FAILED', error
        return True, None
    machine = session.get(Machine, event.machine_id)
    return True, Delivery(row.id, row.attempt_started_at, row.channel,
                          recipient.destination, render_message(event, machine))


def finish(session: Session, delivery: Delivery, error: str | None) -> None:
    row = session.scalar(select(Alert).where(Alert.id == delivery.identifier).with_for_update())
    if row is None or row.status != 'PENDING' or row.attempt_started_at != delivery.started_at:
        raise RuntimeError('delivery_state_changed')
    row.status = 'SENT' if error is None else 'FAILED'
    row.sent_at = database_now(session) if error is None else None
    row.error_message = error

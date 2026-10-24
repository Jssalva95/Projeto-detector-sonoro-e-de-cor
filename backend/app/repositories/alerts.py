"""Queries for transactional enqueueing; no delivery or commits."""

from datetime import datetime

from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from app.models import Alert, AlertRecipient, Event


def latest_fault_transition(session: Session, machine_id: int) -> str | None:
    return session.scalar(select(Event.event_type).where(
        Event.machine_id == machine_id,
        Event.event_type.in_(['FAULT_CONFIRMED', 'FAULT_RECOVERED']),
    ).order_by(Event.id.desc()).limit(1))


def active_recipients(session: Session, channels: tuple[str, ...]) -> list[AlertRecipient]:
    return list(session.scalars(select(AlertRecipient).where(
        AlertRecipient.is_active.is_(True), AlertRecipient.channel.in_(channels),
    ).order_by(AlertRecipient.id)))


def in_cooldown(session: Session, machine_id: int, recipient: AlertRecipient,
                now: datetime, seconds: float) -> bool:
    # Every persisted attempt counts, regardless of delivery status. Comparing
    # elapsed seconds avoids overflowing datetime for large configured values.
    return session.scalar(select(Alert.id).join(Event, Alert.event_id == Event.id).where(
        Event.machine_id == machine_id, Alert.recipient_id == recipient.id,
        Alert.channel == recipient.channel,
        extract('epoch', now - Alert.created_at) < seconds,
    ).limit(1)) is not None


def database_now(session: Session) -> datetime:
    # Unlike now(), this is measured after acquiring the machine lock.
    return session.scalar(select(func.clock_timestamp()))


def insert_pending(session: Session, event: Event, recipient: AlertRecipient,
                   now: datetime) -> None:
    session.add(Alert(event_id=event.id, recipient_id=recipient.id,
                      channel=recipient.channel, status='PENDING', created_at=now))

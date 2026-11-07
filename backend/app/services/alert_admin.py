"""Host-admin operations only; manual retries retain every original attempt."""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.config import mailbox
from app.models import Alert, AlertRecipient, Event
from app.repositories.alerts import database_now


class AlertAdminError(ValueError):
    pass


def add_recipient(session: Session, name: str, channel: str, destination: str) -> AlertRecipient:
    if not name.strip() or any(c in name for c in '\x00\r\n'):
        raise AlertAdminError('invalid_recipient_name')
    if channel == 'EMAIL':
        try:
            mailbox(destination)
        except ValueError:
            raise AlertAdminError('invalid_destination') from None
    elif channel != 'TELEGRAM' or not re.fullmatch(r'-?[0-9]+|@[A-Za-z][A-Za-z0-9_]*', destination):
        raise AlertAdminError('invalid_channel_or_destination')
    recipient = AlertRecipient(name=name, channel=channel, destination=destination, is_active=True)
    session.add(recipient)
    session.flush()
    return recipient


def set_active(session: Session, identifier: int, active: bool) -> None:
    row = session.scalar(select(AlertRecipient).where(AlertRecipient.id == identifier).with_for_update())
    if row is None:
        raise AlertAdminError('recipient_not_found')
    row.is_active = active


def retry(session: Session, identifier: int, *, accept_duplicate_risk: bool,
          workers_stopped: bool = False) -> Alert:
    if not accept_duplicate_risk:
        raise AlertAdminError('explicit_duplicate_risk_acceptance_required')
    original = session.get(Alert, identifier)
    if original is None:
        raise AlertAdminError('alert_not_found')
    # Serialize manual retries for an occurrence before locking its attempt.
    event = session.scalar(select(Event).where(Event.id == original.event_id).with_for_update())
    row = session.scalar(select(Alert).where(Alert.id == identifier).with_for_update()
                         .execution_options(populate_existing=True))
    latest = session.scalar(select(Alert.id).where(
        Alert.event_id == row.event_id, Alert.recipient_id == row.recipient_id,
        Alert.channel == row.channel,
    ).order_by(Alert.id.desc()).limit(1))
    if latest != row.id:
        raise AlertAdminError('newer_attempt_exists')
    if row.status == 'SENT' or (row.status == 'PENDING' and row.attempt_started_at is None):
        raise AlertAdminError('attempt_not_retryable')
    if row.status == 'PENDING' and not workers_stopped:
        raise AlertAdminError('stop_all_workers_before_reconciling_uncertain_attempt')
    recipient = session.get(AlertRecipient, row.recipient_id)
    if (not recipient.is_active or recipient.channel != row.channel
            or row.channel not in ('TELEGRAM', 'EMAIL') or event.event_type != 'FAULT_CONFIRMED'):
        raise AlertAdminError('attempt_not_eligible')
    if row.status == 'PENDING':
        row.status, row.error_message = 'FAILED', 'delivery_unconfirmed'
    new = Alert(event_id=row.event_id, recipient_id=row.recipient_id, channel=row.channel,
                status='PENDING', created_at=database_now(session))
    session.add(new)
    session.flush()
    return new

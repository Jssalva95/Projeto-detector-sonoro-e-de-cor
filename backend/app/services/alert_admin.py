"""Shared CLI/API recipient rules; manual retries retain every original attempt."""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.config import mailbox
from app.models import Alert, AlertRecipient, Event
from app.repositories.alerts import database_now
from app.repositories import alert_admin as repository
from app.schemas.alert_admin import RecipientUpdate


class AlertAdminError(ValueError):
    pass


class AlertAdminNotFound(AlertAdminError):
    pass


class AlertAdminConflict(AlertAdminError):
    pass


def validate_name(name: str) -> None:
    if not name.strip() or any(c in name for c in '\x00\r\n'):
        raise AlertAdminError('invalid_recipient_name')


def validate_destination(channel: str, destination: str) -> None:
    if channel == 'EMAIL':
        try:
            mailbox(destination)
        except ValueError:
            raise AlertAdminError('invalid_destination') from None
    elif channel != 'TELEGRAM' or not re.fullmatch(r'-?[0-9]+|@[A-Za-z][A-Za-z0-9_]*', destination):
        raise AlertAdminError('invalid_channel_or_destination')


def add_recipient(session: Session, name: str, channel: str, destination: str,
                  is_active: bool = True) -> AlertRecipient:
    validate_name(name)
    validate_destination(channel, destination)
    recipient = AlertRecipient(name=name, channel=channel, destination=destination, is_active=is_active)
    session.add(recipient)
    session.flush()
    return recipient


def update_recipient(session: Session, identifier: int, payload: RecipientUpdate) -> AlertRecipient:
    row = repository.recipient(session, identifier, lock=True)
    if row is None:
        raise AlertAdminNotFound('recipient_not_found')
    changes = payload.model_dump(exclude_unset=True)
    channel = changes.get('channel', row.channel)
    destination = changes.get('destination', row.destination)
    identity_changed = channel != row.channel or destination != row.destination
    if identity_changed and repository.has_attempts(session, row.id):
        raise AlertAdminConflict('recipient_identity_has_attempts')
    if 'name' in changes:
        validate_name(changes['name'])
    if identity_changed or changes.get('is_active') is True:
        validate_destination(channel, destination)
    for key, value in changes.items():
        setattr(row, key, value)
    session.flush()
    return row


def set_active(session: Session, identifier: int, active: bool) -> None:
    update_recipient(session, identifier, RecipientUpdate(is_active=active))


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
    recipient = repository.recipient(session, row.recipient_id, lock=True)
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

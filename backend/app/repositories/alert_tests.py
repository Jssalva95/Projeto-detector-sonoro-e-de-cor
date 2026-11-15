"""Serialized UUID/recipient creation and independent durable test reservations."""

from hashlib import blake2b
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import AlertTestAttempt, User
from app.repositories.alert_admin import page, recipient
from app.repositories.alert_delivery import Delivery
from app.repositories.alerts import database_now
from app.schemas.alert_tests import AlertTestFilters


def lock_uuid(session: Session, identifier: UUID) -> None:
    # Global to this request type, including requests for different recipients.
    # Hash collisions only serialize unrelated requests; UNIQUE remains authoritative.
    key = int.from_bytes(blake2b(b'alert-test:' + identifier.bytes, digest_size=8).digest(), 'big', signed=True)
    session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': key})


def requester(session: Session, identifier: int) -> User | None:
    return session.scalar(select(User).where(User.id == identifier).with_for_update(read=True)
                          .execution_options(populate_existing=True))


def by_uuid(session: Session, identifier: UUID) -> AlertTestAttempt | None:
    return session.scalar(select(AlertTestAttempt).where(AlertTestAttempt.uuid == identifier))


def by_id(session: Session, identifier: int, *, lock: bool = False) -> AlertTestAttempt | None:
    statement = select(AlertTestAttempt).where(AlertTestAttempt.id == identifier)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return session.scalar(statement)


def pending(session: Session, recipient_id: int) -> bool:
    return session.scalar(select(AlertTestAttempt.id).where(
        AlertTestAttempt.recipient_id == recipient_id, AlertTestAttempt.status == 'PENDING',
    ).limit(1)) is not None


def latest_created(session: Session, recipient_id: int) -> datetime | None:
    return session.scalar(select(AlertTestAttempt.created_at).where(AlertTestAttempt.recipient_id == recipient_id)
                          .order_by(AlertTestAttempt.created_at.desc(), AlertTestAttempt.id.desc()).limit(1))


def list_attempts(session: Session, filters: AlertTestFilters) -> tuple[int, list[dict[str, object]]]:
    statement = select(*(c for c in AlertTestAttempt.__table__.columns if c.name != 'destination'))
    for name in ('recipient_id', 'status'):
        value = getattr(filters, name)
        if value is not None:
            statement = statement.where(getattr(AlertTestAttempt, name) == value)
    return page(session, AlertTestAttempt, statement, filters.limit, filters.offset,
                descending=True, excluded_columns=frozenset({'destination'}))


def reserve(session: Session, channels: tuple[str, ...]) -> tuple[bool, Delivery | None]:
    if not channels:
        return False, None
    row = session.scalar(select(AlertTestAttempt).where(
        AlertTestAttempt.status == 'PENDING', AlertTestAttempt.attempt_started_at.is_(None),
        AlertTestAttempt.channel.in_(channels),
    ).order_by(AlertTestAttempt.id).limit(1).with_for_update(skip_locked=True).execution_options(populate_existing=True))
    if row is None:
        return False, None
    user = requester(session, row.requested_by)
    target = recipient(session, row.recipient_id, lock=True)
    row.attempt_started_at = max(database_now(session), row.created_at)
    error = None
    if user is None or not user.is_active:
        error = 'requester_inactive'
    elif user.role != 'ADMIN':
        error = 'requester_not_admin'
    elif target is None or not target.is_active:
        error = 'recipient_inactive'
    elif target.channel != row.channel or target.destination != row.destination:
        error = 'recipient_identity_changed'
    if error:
        row.status, row.error_message = 'FAILED', error
        return True, None
    message = ('Olá! Esta é uma mensagem de teste do Machine Monitor.\n'
               'Este envio não representa uma falha de máquina.\n'
               f'Identificador do teste: {row.uuid}')
    return True, Delivery(row.id, row.attempt_started_at, row.channel, row.destination, message)


def finish(session: Session, delivery: Delivery, error: str | None) -> None:
    row = by_id(session, delivery.identifier, lock=True)
    if row is None or row.status != 'PENDING' or row.attempt_started_at != delivery.started_at:
        raise RuntimeError('test_delivery_state_changed')
    row.status = 'SENT' if error is None else 'FAILED'
    row.sent_at = max(database_now(session), row.attempt_started_at) if error is None else None
    row.error_message = error

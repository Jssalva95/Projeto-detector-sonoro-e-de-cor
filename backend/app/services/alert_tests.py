"""Manual test requests: UUID replay, recipient cooldown and no delivery in HTTP."""

import math
from uuid import UUID

from sqlalchemy.orm import Session

from app.alerts.config import email_settings, enabled, telegram_settings, test_cooldown
from app.models import AlertTestAttempt
from app.repositories import alert_tests as repository
from app.repositories.alert_admin import recipient
from app.repositories.alerts import database_now
from app.schemas.alert_tests import AlertTestFilters, AlertTestPage, AlertTestRead
from app.services.alert_admin import AlertAdminConflict, AlertAdminError, AlertAdminNotFound, validate_destination
from app.services.alert_delivery import SAFE_ERRORS

PUBLIC_ERRORS = SAFE_ERRORS | {'requester_inactive', 'requester_not_admin', 'recipient_inactive', 'recipient_identity_changed'}


class CooldownActive(AlertAdminError):
    def __init__(self, remaining: int):
        super().__init__('test_cooldown_active')
        self.retry_after = remaining


class RequesterDenied(AlertAdminError):
    def __init__(self, status_code: int):
        super().__init__('requester_not_authorized')
        self.status_code = status_code


def read(value: AlertTestAttempt | dict[str, object]) -> AlertTestRead:
    result = AlertTestRead.model_validate(value)
    if result.error_message is not None and result.error_message not in PUBLIC_ERRORS:
        result.error_message = 'delivery_unconfirmed'
    return result


def create(session: Session, recipient_id: int, requested_by: int, identifier: UUID) -> tuple[AlertTestAttempt, bool]:
    repository.lock_uuid(session, identifier)
    user = repository.requester(session, requested_by)
    if user is None or not user.is_active:
        raise RequesterDenied(401)
    if user.role != 'ADMIN':
        raise RequesterDenied(403)
    previous = repository.by_uuid(session, identifier)
    if previous is not None:
        if previous.recipient_id != recipient_id or previous.requested_by != requested_by:
            raise AlertAdminConflict('test_uuid_conflict')
        return previous, False
    target = recipient(session, recipient_id, lock=True)
    if target is None:
        raise AlertAdminNotFound('recipient_not_found')
    if not target.is_active or target.channel not in ('EMAIL', 'TELEGRAM'):
        raise AlertAdminConflict('recipient_not_eligible')
    if not enabled(target.channel + '_ENABLED'):
        raise AlertAdminConflict('channel_disabled')
    if repository.pending(session, recipient_id):
        raise AlertAdminConflict('test_pending')
    try:
        validate_destination(target.channel, target.destination)
    except AlertAdminError:
        raise AlertAdminConflict('recipient_not_eligible') from None
    email_settings() if target.channel == 'EMAIL' else telegram_settings()
    cooldown = test_cooldown()
    now = database_now(session)
    latest = repository.latest_created(session, recipient_id)
    if latest is not None:
        remaining = cooldown - (now - latest).total_seconds()
        if remaining > 0:
            raise CooldownActive(math.ceil(remaining))
    row = AlertTestAttempt(uuid=identifier, recipient_id=recipient_id, requested_by=requested_by,
                           channel=target.channel, destination=target.destination,
                           status='PENDING', created_at=now)
    session.add(row)
    session.flush()
    return row, True


def get(session: Session, identifier: int) -> AlertTestRead:
    row = repository.by_id(session, identifier)
    if row is None:
        raise AlertAdminNotFound('test_not_found')
    return read(row)


def list_attempts(session: Session, filters: AlertTestFilters) -> AlertTestPage:
    total, rows = repository.list_attempts(session, filters)
    return AlertTestPage(total=total, limit=filters.limit, offset=filters.offset, items=[read(row) for row in rows])


def reconcile(session: Session, identifier: int, *, workers_stopped: bool) -> AlertTestAttempt:
    if not workers_stopped:
        raise AlertAdminError('stop_all_workers_before_reconciling_uncertain_attempt')
    row = repository.by_id(session, identifier, lock=True)
    if row is None:
        raise AlertAdminNotFound('test_not_found')
    if row.status != 'PENDING' or row.attempt_started_at is None:
        raise AlertAdminConflict('test_not_uncertain')
    row.status, row.error_message = 'FAILED', 'delivery_unconfirmed'
    session.flush()
    return row

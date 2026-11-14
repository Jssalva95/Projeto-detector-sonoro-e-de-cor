"""Admin read models: exact settings allowlist and sanitized alert failures."""

from sqlalchemy.orm import Session

from app.alerts.config import email_settings, enabled, poll_interval, queue_settings, telegram_settings, test_cooldown
from app.models import Alert
from app.repositories import alert_admin as repository
from app.schemas.alert_admin import AlertFilters, AlertPage, OperationalSettings, RecipientFilters, RecipientPage
from app.schemas.domain import AlertRead, AlertRecipientRead
from app.services.alert_admin import AlertAdminNotFound
from app.services.alert_delivery import SAFE_ERRORS

PUBLIC_ERRORS = SAFE_ERRORS | {'recipient_inactive', 'recipient_channel_changed', 'invalid_alert_event'}


def public_alert(value: Alert | dict[str, object]) -> AlertRead:
    result = AlertRead.model_validate(value)
    if result.error_message is not None and result.error_message not in PUBLIC_ERRORS:
        result.error_message = 'delivery_unconfirmed'
    return result


def get_recipient(session: Session, identifier: int) -> AlertRecipientRead:
    row = repository.recipient(session, identifier)
    if row is None:
        raise AlertAdminNotFound('recipient_not_found')
    return AlertRecipientRead.model_validate(row)


def recipients(session: Session, filters: RecipientFilters) -> RecipientPage:
    total, rows = repository.recipients(session, filters.channel, filters.is_active, filters.limit, filters.offset)
    return RecipientPage(total=total, limit=filters.limit, offset=filters.offset,
                         items=[AlertRecipientRead.model_validate(row) for row in rows])


def get_alert(session: Session, identifier: int) -> AlertRead:
    row = session.get(Alert, identifier)
    if row is None:
        raise AlertAdminNotFound('alert_not_found')
    return public_alert(row)


def alerts(session: Session, filters: AlertFilters) -> AlertPage:
    total, rows = repository.alerts(session, filters.model_dump(exclude={'limit', 'offset'}), filters.limit, filters.offset)
    return AlertPage(total=total, limit=filters.limit, offset=filters.offset, items=[public_alert(row) for row in rows])


def settings() -> OperationalSettings:
    email, telegram = enabled('EMAIL_ENABLED'), enabled('TELEGRAM_ENABLED')
    if not (email or telegram):
        return OperationalSettings(email_enabled=False, telegram_enabled=False, alert_cooldown_seconds=None,
                                   alert_poll_interval_seconds=None, alert_test_cooldown_seconds=None)
    # Validate enabled configuration locally, without constructing a provider or
    # performing DNS/TLS/login. Never serialize these credential-bearing models.
    email_settings()
    telegram_settings()
    _, cooldown = queue_settings()
    return OperationalSettings(email_enabled=email, telegram_enabled=telegram, alert_cooldown_seconds=cooldown,
                               alert_poll_interval_seconds=poll_interval(), alert_test_cooldown_seconds=test_cooldown())

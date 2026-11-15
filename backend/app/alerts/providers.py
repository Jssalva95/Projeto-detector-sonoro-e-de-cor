"""Build enabled providers without connecting or sending anything."""

from app.alerts.base import AlertProvider
from app.alerts.config import email_settings, telegram_settings
from app.alerts.email import EmailProvider
from app.alerts.telegram import TelegramProvider


def providers_for_tests(providers: dict[str, AlertProvider]) -> dict[str, AlertProvider]:
    """Same transports/configuration; only the fixed email subject differs."""
    result = dict(providers)
    email = providers.get('EMAIL')
    if isinstance(email, EmailProvider):
        result['EMAIL'] = EmailProvider(email.settings, purpose='test')
    return result


def configured_providers() -> dict[str, AlertProvider]:
    telegram = telegram_settings()
    email = email_settings()
    result: dict[str, AlertProvider] = {}
    if telegram is not None:
        result['TELEGRAM'] = TelegramProvider(telegram)
    if email is not None:
        result['EMAIL'] = EmailProvider(email)
    return result

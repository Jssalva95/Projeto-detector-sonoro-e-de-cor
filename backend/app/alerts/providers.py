"""Build enabled providers without connecting or sending anything."""

from app.alerts.base import AlertProvider
from app.alerts.config import email_settings, telegram_settings
from app.alerts.email import EmailProvider
from app.alerts.telegram import TelegramProvider


def configured_providers() -> dict[str, AlertProvider]:
    telegram = telegram_settings()
    email = email_settings()
    result: dict[str, AlertProvider] = {}
    if telegram is not None:
        result['TELEGRAM'] = TelegramProvider(telegram)
    if email is not None:
        result['EMAIL'] = EmailProvider(email)
    return result

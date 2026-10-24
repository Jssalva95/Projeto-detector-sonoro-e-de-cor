"""Explicit, channel-scoped configuration; disabled channels need no secrets."""

import os
import re
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator, model_validator


class AlertConfigurationError(ValueError):
    pass


def mailbox(value: str) -> str:
    # One plain ASCII addr-spec, no display names, lists or header controls.
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", value):
        raise ValueError('Expected one plain email address')
    local, domain = value.rsplit('@', 1)
    if local.startswith('.') or local.endswith('.') or '..' in local or '..' in domain:
        raise ValueError('Invalid email address')
    return value


Timeout = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class TelegramSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    token: SecretStr = Field(repr=False)
    timeout: Timeout

    @field_validator('token')
    @classmethod
    def valid_token(cls, value: SecretStr) -> SecretStr:
        if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', value.get_secret_value()):
            raise ValueError('Invalid bot token format')
        return value


class EmailSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    host: str
    port: Annotated[int, Field(ge=1, le=65535)]
    tls_mode: Literal['starttls', 'ssl']
    timeout: Timeout
    sender: str
    username: str = Field(default='', repr=False)
    password: SecretStr = Field(default=SecretStr(''), repr=False)

    @field_validator('host')
    @classmethod
    def valid_host(cls, value: str) -> str:
        if not value or any(c.isspace() or ord(c) < 32 for c in value) or '/' in value:
            raise ValueError('Invalid SMTP host')
        return value

    @field_validator('sender')
    @classmethod
    def valid_sender(cls, value: str) -> str:
        return mailbox(value)

    @model_validator(mode='after')
    def paired_credentials(self) -> Self:
        if bool(self.username) != bool(self.password.get_secret_value()):
            raise ValueError('SMTP credentials must be supplied together')
        if any(c in self.username for c in '\r\n\x00'):
            raise ValueError('Invalid SMTP username')
        return self


def enabled(name: str) -> bool:
    value = os.environ.get(name, '').strip().lower()
    if value in ('', 'false'):
        return False
    if value == 'true':
        return True
    raise AlertConfigurationError(f'{name} must be true or false')


def telegram_settings() -> TelegramSettings | None:
    if not enabled('TELEGRAM_ENABLED'):
        return None
    try:
        return TelegramSettings(token=os.environ.get('TELEGRAM_BOT_TOKEN', ''),
                                timeout=os.environ.get('TELEGRAM_TIMEOUT_SECONDS', ''))
    except ValidationError:
        raise AlertConfigurationError('Invalid or incomplete Telegram configuration') from None


def email_settings() -> EmailSettings | None:
    if not enabled('EMAIL_ENABLED'):
        return None
    try:
        return EmailSettings(host=os.environ.get('SMTP_HOST', ''), port=os.environ.get('SMTP_PORT', ''),
                             tls_mode=os.environ.get('SMTP_TLS_MODE', ''),
                             timeout=os.environ.get('SMTP_TIMEOUT_SECONDS', ''),
                             sender=os.environ.get('SMTP_FROM', ''), username=os.environ.get('SMTP_USER', ''),
                             password=os.environ.get('SMTP_PASSWORD', ''))
    except ValidationError:
        raise AlertConfigurationError('Invalid or incomplete email configuration') from None

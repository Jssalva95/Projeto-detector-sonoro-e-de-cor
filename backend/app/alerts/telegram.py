"""Telegram plain-text delivery, one request, no retries or redirects."""

import logging
import re

import httpx

from app.alerts.base import ProviderError
from app.alerts.config import TelegramSettings


class _RedactBotURL(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # HTTPX logs request URLs at INFO, and Telegram carries the token in its URL.
        record.msg = re.sub(r'(api\.telegram\.org/bot)[^/\s"\']+', r'\1[REDACTED]', record.getMessage())
        record.args = ()
        return True


class TelegramProvider:
    def __init__(self, settings: TelegramSettings, *, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.transport = transport
        logger = logging.getLogger('httpx')
        if not any(isinstance(item, _RedactBotURL) for item in logger.filters):
            logger.addFilter(_RedactBotURL())

    async def send(self, message: str, destination: str) -> None:
        if not message or len(message) > 4096 or '\x00' in message:
            raise ProviderError('invalid_message')
        if not re.fullmatch(r'-?[0-9]+|@[A-Za-z][A-Za-z0-9_]*', destination):
            raise ProviderError('invalid_destination')
        try:
            message.encode('utf-8')
        except UnicodeError:
            raise ProviderError('invalid_message') from None
        url = 'https://api.telegram.org/bot' + self.settings.token.get_secret_value() + '/sendMessage'
        try:
            async with httpx.AsyncClient(timeout=self.settings.timeout, follow_redirects=False,
                                         trust_env=False, transport=self.transport) as client:
                response = await client.post(url, json={'chat_id': destination, 'text': message})
            if response.status_code != 200:
                raise ProviderError('telegram_rejected' if 400 <= response.status_code < 500 else 'delivery_unconfirmed')
            data = response.json()
            if not isinstance(data, dict) or data.get('ok') is not True:
                raise ProviderError('telegram_rejected' if isinstance(data, dict) and data.get('ok') is False else 'delivery_unconfirmed')
            result = data.get('result')
            if not isinstance(result, dict) or type(result.get('message_id')) is not int:
                raise ProviderError('delivery_unconfirmed')
        except (httpx.HTTPError, ValueError, UnicodeError):
            # Never expose response bodies, URLs or exception text carrying tokens.
            raise ProviderError('delivery_unconfirmed') from None

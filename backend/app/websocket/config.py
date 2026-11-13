"""Explicit WebSocket limits and exact browser-origin allowlist."""

import json
import math
import os
from dataclasses import dataclass
from urllib.parse import urlsplit


class WebSocketConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class WebSocketSettings:
    auth_timeout: float
    send_timeout: float
    max_message_bytes: int
    allowed_origins: frozenset[str]
    client_queue_size: int


def websocket_settings() -> WebSocketSettings:
    try:
        auth = float(os.environ.get('WS_AUTH_TIMEOUT_SECONDS', ''))
        send = float(os.environ.get('WS_SEND_TIMEOUT_SECONDS', ''))
        size = int(os.environ.get('WS_MAX_MESSAGE_BYTES', ''))
        queue_size = int(os.environ.get('WS_CLIENT_QUEUE_SIZE', ''))
        if (not all(math.isfinite(value) and value > 0 for value in (auth, send))
                or size <= 0 or queue_size <= 0):
            raise ValueError
        origins = json.loads(os.environ.get('WS_ALLOWED_ORIGINS', ''))
        if not isinstance(origins, list) or not origins:
            raise ValueError
        for origin in origins:
            if not isinstance(origin, str) or any(c.isspace() for c in origin):
                raise ValueError
            parts = urlsplit(origin)
            if (parts.scheme not in ('http', 'https') or not parts.hostname
                    or parts.username is not None or parts.password is not None
                    or parts.path or parts.query or parts.fragment
                    or '*' in origin or parts.port == 0 or origin.endswith(':')
                    or origin != f'{parts.scheme}://{parts.netloc}'):
                raise ValueError
        return WebSocketSettings(auth, send, size, frozenset(origins), queue_size)
    except (ValueError, TypeError, OverflowError):
        raise WebSocketConfigurationError('Invalid or missing WebSocket configuration') from None

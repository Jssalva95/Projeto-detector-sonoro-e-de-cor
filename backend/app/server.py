"""Shared Docker/Windows entrypoint with explicit WebSocket transport limits."""

from copy import deepcopy
import logging
import os
import re

import uvicorn
from uvicorn.config import LOGGING_CONFIG

from app.websocket.config import websocket_settings


class TransportLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Protocol DEBUG/TRACE may contain authentication frames or headers.
        if record.levelno < logging.INFO:
            return False
        if record.name == 'uvicorn.access' and isinstance(record.args, tuple) and len(record.args) == 5:
            client, method, path, version, status = record.args
            # AccessFormatter needs this tuple intact to construct request_line.
            path = re.sub(r'(/api/v1/ws/events)\?[^\s\"\']*', r'\1?[REDACTED]', path)
            record.args = (client, method, path, version, status)
            return True
        message = record.getMessage()
        record.msg = re.sub(r'(/api/v1/ws/events)\?[^\s\"\']*', r'\1?[REDACTED]', message)
        record.args = ()
        return True


def main() -> int:
    try:
        settings = websocket_settings()
        port = int(os.environ['BACKEND_PORT'])
        if not 1 <= port <= 65535:
            raise ValueError
    except (ValueError, KeyError):
        logging.getLogger(__name__).error('server_configuration_invalid')
        return 1
    log_config = deepcopy(LOGGING_CONFIG)
    log_config['filters'] = {'ws_safe': {'()': TransportLogFilter}}
    for handler in log_config['handlers'].values():
        handler['filters'] = ['ws_safe']
    uvicorn.run('app.main:app', host='0.0.0.0', port=port, workers=1,
                ws='websockets', ws_max_size=settings.max_message_bytes,
                ws_per_message_deflate=False, ws_ping_interval=None,
                log_config=log_config)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

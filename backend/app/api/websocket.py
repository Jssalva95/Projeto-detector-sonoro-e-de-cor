"""Authenticate, acknowledge and stream committed critical events."""

import asyncio
from datetime import datetime, timezone
import logging

from fastapi import APIRouter, WebSocket
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocketDisconnect

from app.security import InvalidCredentials
from app.websocket.auth import ForbiddenUser, Principal, authenticate
from app.websocket.config import websocket_settings
from app.websocket.connection import AuthenticatedConnection, ProtocolViolation, receive_text
from app.websocket.schemas import AuthenticatedMessage, AuthenticationMessage
from app.websocket.manager import connection_manager

router = APIRouter()
logger = logging.getLogger(__name__)


async def initial_authentication(socket: WebSocket, limit: int) -> Principal:
    raw = await receive_text(socket, limit)
    payload = AuthenticationMessage.model_validate_json(raw)
    return await run_in_threadpool(authenticate, payload.access_token.get_secret_value())


@router.websocket('/api/v1/ws/events')
async def events_socket(socket: WebSocket) -> None:
    code = 1011
    try:
        settings = websocket_settings()
        origins = socket.headers.getlist('origin')
        if (len(origins) != 1 or origins[0] not in settings.allowed_origins
                or socket.scope.get('query_string')):
            await socket.close(code=1008)  # Before accept: HTTP 403, not a WS close frame.
            return
        await socket.accept()
        try:
            principal = await asyncio.wait_for(initial_authentication(socket, settings.max_message_bytes),
                                               settings.auth_timeout)
        except TimeoutError:
            code = 4408
        else:
            connection = AuthenticatedConnection(socket, principal, settings)
            await connection.send(AuthenticatedMessage(
                expires_at=datetime.fromtimestamp(principal.expires_at, timezone.utc)))
            await connection_manager(socket).serve(connection, settings.client_queue_size)
    except WebSocketDisconnect:
        return
    except InvalidCredentials:
        code = 4401
    except ForbiddenUser:
        code = 4403
    except ValidationError:
        code = 1008  # Never echo the first message or Pydantic's input/ctx.
    except ProtocolViolation as error:
        code = error.code
    except Exception:
        logger.warning('websocket_operational_failure')
    try:
        await socket.close(code=code)
    except (WebSocketDisconnect, OSError, RuntimeError):
        # Transport already closed; no retry or raw exception logging.
        logger.debug('websocket_already_closed')

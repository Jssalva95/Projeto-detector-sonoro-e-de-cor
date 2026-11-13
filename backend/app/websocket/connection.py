"""Authenticated sends and receive/expiry monitoring for a single connection."""

import asyncio
import time

from fastapi import WebSocket
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocketDisconnect

from app.security import InvalidCredentials
from app.websocket.auth import Principal, revalidate
from app.websocket.config import WebSocketSettings
from app.websocket.schemas import AuthenticatedMessage, EventNotification


class ProtocolViolation(ValueError):
    def __init__(self, code: int):
        self.code = code


async def receive_text(socket: WebSocket, limit: int) -> str:
    message = await socket.receive()
    if message['type'] == 'websocket.disconnect':
        raise WebSocketDisconnect(message.get('code', 1000))
    raw = message.get('text')
    if raw is None:
        raise ProtocolViolation(1003)
    if len(raw.encode('utf-8')) > limit:
        raise ProtocolViolation(1009)
    return raw


class AuthenticatedConnection:
    def __init__(self, socket: WebSocket, principal: Principal, settings: WebSocketSettings):
        self.socket = socket
        self.principal = principal
        self.settings = settings

    async def send(self, message: AuthenticatedMessage | EventNotification) -> None:
        # Queries current activity and role before each send.
        await run_in_threadpool(revalidate, self.principal)
        remaining = self.principal.expires_at - time.time()
        if remaining <= 0:
            raise InvalidCredentials('Invalid credentials')
        try:
            await asyncio.wait_for(self.socket.send_json(message.model_dump(mode='json')),
                                   timeout=min(self.settings.send_timeout, remaining))
        except TimeoutError:
            if self.principal.expires_at <= time.time():
                raise InvalidCredentials('Invalid credentials') from None
            raise

    async def wait_for_disconnect(self) -> None:
        remaining = self.principal.expires_at - time.time()
        if remaining <= 0:
            raise InvalidCredentials('Invalid credentials')
        try:
            await asyncio.wait_for(receive_text(self.socket, self.settings.max_message_bytes), remaining)
        except TimeoutError:
            raise InvalidCredentials('Invalid credentials') from None
        # Read-only protocol. No token replacement or application commands.
        raise ProtocolViolation(1008)

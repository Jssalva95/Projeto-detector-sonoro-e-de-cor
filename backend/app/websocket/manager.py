"""Process-local, best-effort fan-out; every connection owns a bounded queue."""

import asyncio
from dataclasses import dataclass, field
import logging

from starlette.requests import HTTPConnection

from app.websocket.connection import AuthenticatedConnection, ProtocolViolation
from app.websocket.schemas import EventNotification

logger = logging.getLogger(__name__)


@dataclass(eq=False)
class Subscriber:
    queue: asyncio.Queue[EventNotification]
    overflow: asyncio.Event = field(default_factory=asyncio.Event)


class ConnectionManager:
    def __init__(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.subscribers: set[Subscriber] = set()

    def publish(self, notification: EventNotification) -> None:
        """Called after commit from a request thread; never wait for a socket."""
        try:
            self.loop.call_soon_threadsafe(self._offer, notification)
        except RuntimeError:
            logger.warning('websocket_publication_unavailable')

    def _offer(self, notification: EventNotification) -> None:
        for subscriber in tuple(self.subscribers):
            try:
                subscriber.queue.put_nowait(notification)
            except asyncio.QueueFull:
                self.subscribers.discard(subscriber)
                subscriber.overflow.set()

    async def serve(self, connection: AuthenticatedConnection, capacity: int) -> None:
        subscriber = Subscriber(asyncio.Queue(maxsize=capacity))
        self.subscribers.add(subscriber)

        async def send() -> None:
            while True:
                await connection.send(await subscriber.queue.get())

        async def overflow() -> None:
            await subscriber.overflow.wait()
            raise ProtocolViolation(1013)

        tasks = [asyncio.create_task(connection.wait_for_disconnect()),
                 asyncio.create_task(send()), asyncio.create_task(overflow())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            # Retrieve all outcomes during cleanup, even if multiple tasks fail.
            for task in tasks:
                if task in done:
                    task.result()
        finally:
            self.subscribers.discard(subscriber)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


def connection_manager(connection: HTTPConnection) -> ConnectionManager:
    """Only called on the ASGI loop; test app lifecycles may use a new loop."""
    manager = getattr(connection.app.state, 'event_connections', None)
    if manager is None or manager.loop is not asyncio.get_running_loop():
        manager = ConnectionManager()
        connection.app.state.event_connections = manager
    return manager

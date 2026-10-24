"""Small delivery contract. Success means provider acceptance, not receipt."""

from typing import Protocol


class ProviderError(RuntimeError):
    """Safe error codes only: never include credentials, payloads or server replies."""


class AlertProvider(Protocol):
    async def send(self, message: str, destination: str) -> None: ...

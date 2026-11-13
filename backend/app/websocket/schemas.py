"""Wire contracts: internal BIGINT identifiers, UUID occurrence and UTC time."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.models.enums import Severity
from app.schemas.domain import Identifier, UtcDateTime


class AuthenticationMessage(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    type: Literal['authenticate']
    access_token: SecretStr = Field(repr=False, min_length=1)


class AuthenticatedMessage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['authenticated'] = 'authenticated'
    expires_at: UtcDateTime


class EventNotification(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    type: Literal['FAULT_CONFIRMED', 'FAULT_RECOVERED', 'DEVICE_OFFLINE', 'DEVICE_ONLINE']
    event_id: Identifier
    uuid: UUID
    machine_id: Identifier
    timestamp: UtcDateTime
    severity: Severity

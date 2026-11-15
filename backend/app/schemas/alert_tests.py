"""ADMIN test-send requests and explicit responses excluding the destination snapshot."""

from typing import Annotated
from uuid import UUID

from pydantic import Field

from app.models.enums import AlertStatus
from app.schemas.alert_admin import PageFilters, SupportedChannel
from app.schemas.domain import Created, DataSchema, Identifier, UtcDateTime


class AlertTestRequest(DataSchema):
    uuid: UUID


class AlertTestRead(Created):
    uuid: UUID
    recipient_id: Identifier
    requested_by: Identifier
    channel: SupportedChannel
    status: AlertStatus
    attempt_started_at: UtcDateTime | None
    sent_at: UtcDateTime | None
    error_message: str | None


class AlertTestFilters(PageFilters):
    recipient_id: Identifier | None = None
    status: AlertStatus | None = None


class AlertTestPage(PageFilters):
    total: Annotated[int, Field(ge=0)]
    items: list[AlertTestRead]

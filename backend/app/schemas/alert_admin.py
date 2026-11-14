"""Admin-only recipient mutations, query envelopes and safe operational settings."""

from typing import Annotated, Literal

from pydantic import Field

from app.models.enums import AlertStatus, Channel
from app.schemas.domain import AlertRead, AlertRecipientRead, DataSchema, Identifier
from app.schemas.equipment import PartialUpdate

SupportedChannel = Literal['EMAIL', 'TELEGRAM']


class RecipientRequest(DataSchema):
    name: str
    channel: SupportedChannel
    destination: str
    is_active: bool = True


class RecipientUpdate(PartialUpdate):
    name: str | None = None
    channel: SupportedChannel | None = None
    destination: str | None = None
    is_active: bool | None = None


class PageFilters(DataSchema):
    limit: Annotated[int, Field(ge=1, le=200)] = 50
    offset: Annotated[int, Field(ge=0, le=9223372036854775807)] = 0


class RecipientFilters(PageFilters):
    channel: Channel | None = None
    is_active: bool | None = None


class AlertFilters(PageFilters):
    event_id: Identifier | None = None
    recipient_id: Identifier | None = None
    machine_id: Identifier | None = None
    channel: Channel | None = None
    status: AlertStatus | None = None


class RecipientPage(PageFilters):
    total: Annotated[int, Field(ge=0)]
    items: list[AlertRecipientRead]


class AlertPage(PageFilters):
    total: Annotated[int, Field(ge=0)]
    items: list[AlertRead]


class OperationalSettings(DataSchema):
    email_enabled: bool
    telegram_enabled: bool
    alert_cooldown_seconds: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None
    alert_poll_interval_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None
    alert_test_cooldown_seconds: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None

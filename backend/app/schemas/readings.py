"""Approved telemetry query contract."""

from typing import Annotated, Self

from pydantic import Field, model_validator

from app.models.enums import Color
from app.schemas.domain import DataSchema, Identifier, UtcDateTime


class ReadingFilters(DataSchema):
    machine_id: Identifier | None = None
    start_date: UtcDateTime | None = None
    end_date: UtcDateTime | None = None
    color: Color | None = None
    sound_detected: bool | None = None
    limit: Annotated[int, Field(ge=1, le=200)] = 50
    offset: Annotated[int, Field(ge=0, le=9223372036854775807)] = 0

    @model_validator(mode="after")
    def ordered_dates(self) -> Self:
        if self.start_date is not None and self.end_date is not None:
            if self.start_date > self.end_date:
                raise ValueError("start_date must not exceed end_date")
        return self

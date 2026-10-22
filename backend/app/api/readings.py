"""Device-key ingestion and access-token telemetry queries."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_session, require_device_key, require_roles
from app.models.enums import Role
from app.schemas.domain import Identifier, SensorReadingCreate, SensorReadingRead
from app.schemas.readings import ReadingFilters
from app.services import readings

router = APIRouter(prefix="/api/v1/readings", tags=["Readings"])
SessionDependency = Annotated[Session, Depends(get_session)]
read_access = [Depends(require_roles(Role.ADMIN, Role.OPERATOR, Role.VIEWER))]


@router.post("", response_model=SensorReadingRead, status_code=201,
             dependencies=[Depends(require_device_key)])
def create(payload: SensorReadingCreate, session: SessionDependency) -> SensorReadingRead:
    return SensorReadingRead.model_validate(readings.create(session, payload))


@router.get("", response_model=list[SensorReadingRead], dependencies=read_access)
def list_readings(filters: Annotated[ReadingFilters, Query()],
                  session: SessionDependency) -> list[SensorReadingRead]:
    return [SensorReadingRead.model_validate(row) for row in readings.list_readings(session, filters)]


@router.get("/{id}", response_model=SensorReadingRead, dependencies=read_access)
def get(id: Identifier, session: SessionDependency) -> SensorReadingRead:
    return SensorReadingRead.model_validate(readings.get(session, id))

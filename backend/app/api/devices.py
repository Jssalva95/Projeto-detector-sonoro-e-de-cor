"""Device management uses user RBAC; heartbeat uses only the device API key."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.dependencies import get_session, require_device_key, require_roles
from app.models.enums import Role
from app.schemas.domain import DeviceCreate, DeviceRead, Identifier
from app.schemas.equipment import DeviceHeartbeatRequest, DeviceUpdate
from app.services import equipment

router = APIRouter(prefix="/api/v1/devices", tags=["Devices"])
SessionDependency = Annotated[Session, Depends(get_session)]
admin_only = [Depends(require_roles(Role.ADMIN))]
read_access = [Depends(require_roles(Role.ADMIN, Role.OPERATOR, Role.VIEWER))]


@router.post("/heartbeat", response_model=DeviceRead, dependencies=[Depends(require_device_key)])
def heartbeat(payload: DeviceHeartbeatRequest, session: SessionDependency) -> DeviceRead:
    return DeviceRead.model_validate(equipment.heartbeat(session, payload))


@router.post("", response_model=DeviceRead, status_code=201, dependencies=admin_only)
def create(payload: DeviceCreate, session: SessionDependency) -> DeviceRead:
    return DeviceRead.model_validate(equipment.create_device(session, payload))


@router.get("", response_model=list[DeviceRead], dependencies=read_access)
def list_devices(session: SessionDependency) -> list[DeviceRead]:
    return [DeviceRead.model_validate(row) for row in equipment.list_devices(session)]


@router.get("/{id}", response_model=DeviceRead, dependencies=read_access)
def get(id: Identifier, session: SessionDependency) -> DeviceRead:
    return DeviceRead.model_validate(equipment.get_device(session, id))


@router.patch("/{id}", response_model=DeviceRead, dependencies=admin_only)
def update(id: Identifier, payload: DeviceUpdate, session: SessionDependency) -> DeviceRead:
    return DeviceRead.model_validate(equipment.update_device(session, id, payload))


@router.delete("/{id}", status_code=204, dependencies=admin_only)
def delete(id: Identifier, session: SessionDependency) -> Response:
    equipment.delete_device(session, id)
    return Response(status_code=204)

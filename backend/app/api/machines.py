"""Machine HTTP endpoints; policies and writes live in the service."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.dependencies import get_session, require_roles
from app.models.enums import Role
from app.schemas.domain import Identifier, MachineCreate, MachineRead
from app.schemas.equipment import MachineUpdate
from app.services import equipment

router = APIRouter(prefix="/api/v1/machines", tags=["Machines"],
                   dependencies=[Depends(require_roles(Role.ADMIN, Role.OPERATOR, Role.VIEWER))])
SessionDependency = Annotated[Session, Depends(get_session)]
admin_only = [Depends(require_roles(Role.ADMIN))]


@router.post("", response_model=MachineRead, status_code=201, dependencies=admin_only)
def create(payload: MachineCreate, session: SessionDependency) -> MachineRead:
    return MachineRead.model_validate(equipment.create_machine(session, payload))


@router.get("", response_model=list[MachineRead])
def list_machines(session: SessionDependency) -> list[MachineRead]:
    return [MachineRead.model_validate(row) for row in equipment.list_machines(session)]


@router.get("/{id}", response_model=MachineRead)
def get(id: Identifier, session: SessionDependency) -> MachineRead:
    return MachineRead.model_validate(equipment.get_machine(session, id))


@router.patch("/{id}", response_model=MachineRead, dependencies=admin_only)
def update(id: Identifier, payload: MachineUpdate, session: SessionDependency) -> MachineRead:
    return MachineRead.model_validate(equipment.update_machine(session, id, payload))


@router.delete("/{id}", status_code=204, dependencies=admin_only)
def delete(id: Identifier, session: SessionDependency) -> Response:
    equipment.delete_machine(session, id)
    return Response(status_code=204)

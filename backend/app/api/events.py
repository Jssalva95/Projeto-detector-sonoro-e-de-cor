"""Device-key ingestion, user queries and authorized acknowledgment."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.api.dependencies import get_session, require_device_key, require_roles
from app.models import User
from app.models.enums import Role
from app.schemas.domain import EventRead, Identifier
from app.schemas.events import EventFilters, EventRequest
from app.services import events

router = APIRouter(prefix="/api/v1/events", tags=["Events"])
SessionDependency = Annotated[Session, Depends(get_session)]
read_access = [Depends(require_roles(Role.ADMIN, Role.OPERATOR, Role.VIEWER))]
AcknowledgingUser = Annotated[User, Depends(require_roles(Role.ADMIN, Role.OPERATOR))]


@router.post("", response_model=EventRead, status_code=201,
             responses={200: {"model": EventRead, "description": "Identical retransmission"}},
             dependencies=[Depends(require_device_key)])
def create(payload: EventRequest, session: SessionDependency, response: Response) -> EventRead:
    event, created = events.create(session, payload)
    response.status_code = 201 if created else 200
    return EventRead.model_validate(event)


@router.get("", response_model=list[EventRead], dependencies=read_access)
def list_events(filters: Annotated[EventFilters, Query()], session: SessionDependency) -> list[EventRead]:
    return [EventRead.model_validate(row) for row in events.list_events(session, filters)]


@router.get("/{id}", response_model=EventRead, dependencies=read_access)
def get(id: Identifier, session: SessionDependency) -> EventRead:
    return EventRead.model_validate(events.get(session, id))


async def no_acknowledgment_body(request: Request) -> None:
    if await request.body():
        raise HTTPException(422, "Acknowledgment does not accept a request body")


@router.post("/{id}/acknowledge", response_model=EventRead,
             dependencies=[Depends(no_acknowledgment_body)])
def acknowledge(id: Identifier, session: SessionDependency, user: AcknowledgingUser) -> EventRead:
    return EventRead.model_validate(events.acknowledge(session, id, user.id))

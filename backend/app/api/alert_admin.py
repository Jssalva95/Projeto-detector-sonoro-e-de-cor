"""ADMIN-only recipient administration and read-only alert/settings routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.dependencies import get_session, require_roles
from app.models.enums import Role
from app.schemas.alert_admin import (
    AlertFilters, AlertPage, OperationalSettings, RecipientFilters, RecipientPage, RecipientRequest, RecipientUpdate,
)
from app.schemas.domain import AlertRead, AlertRecipientRead, Identifier
from app.services import alert_admin, alert_queries


def no_store(response: Response) -> None:
    response.headers['Cache-Control'] = 'no-store'


router = APIRouter(prefix='/api/v1', tags=['Alert administration'],
                   dependencies=[Depends(require_roles(Role.ADMIN)), Depends(no_store)])
SessionDependency = Annotated[Session, Depends(get_session)]


@router.get('/alert-recipients', response_model=RecipientPage)
def recipients(filters: Annotated[RecipientFilters, Query()], session: SessionDependency) -> RecipientPage:
    return alert_queries.recipients(session, filters)


@router.get('/alert-recipients/{id}', response_model=AlertRecipientRead)
def recipient(id: Identifier, session: SessionDependency) -> AlertRecipientRead:
    return alert_queries.get_recipient(session, id)


@router.post('/alert-recipients', response_model=AlertRecipientRead, status_code=201)
def create(payload: RecipientRequest, session: SessionDependency) -> AlertRecipientRead:
    return AlertRecipientRead.model_validate(alert_admin.add_recipient(session, **payload.model_dump()))


@router.patch('/alert-recipients/{id}', response_model=AlertRecipientRead)
def update(id: Identifier, payload: RecipientUpdate, session: SessionDependency) -> AlertRecipientRead:
    return AlertRecipientRead.model_validate(alert_admin.update_recipient(session, id, payload))


@router.get('/alerts', response_model=AlertPage)
def alerts(filters: Annotated[AlertFilters, Query()], session: SessionDependency) -> AlertPage:
    return alert_queries.alerts(session, filters)


@router.get('/alerts/{id}', response_model=AlertRead)
def alert(id: Identifier, session: SessionDependency) -> AlertRead:
    return alert_queries.get_alert(session, id)


@router.get('/settings', response_model=OperationalSettings)
def settings() -> OperationalSettings:
    return alert_queries.settings()

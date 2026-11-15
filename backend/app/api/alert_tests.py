"""Admin-only requests enqueue test sends; no external I/O in the API process."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.alert_admin import no_store
from app.api.dependencies import current_user, get_session, require_roles
from app.models import User
from app.models.enums import Role
from app.schemas.alert_tests import AlertTestFilters, AlertTestPage, AlertTestRead, AlertTestRequest
from app.schemas.domain import Identifier
from app.services import alert_tests

router = APIRouter(prefix='/api/v1', tags=['Alert tests'],
                   dependencies=[Depends(require_roles(Role.ADMIN)), Depends(no_store)])
SessionDependency = Annotated[Session, Depends(get_session)]


@router.post('/alert-recipients/{id}/test', response_model=AlertTestRead, status_code=202,
             responses={200: {'model': AlertTestRead, 'description': 'Identical UUID replay'}})
def create(id: Identifier, payload: AlertTestRequest, session: SessionDependency,
           user: Annotated[User, Depends(current_user)], response: Response) -> AlertTestRead:
    row, created = alert_tests.create(session, id, user.id, payload.uuid)
    response.status_code = 202 if created else 200
    return alert_tests.read(row)


@router.get('/alert-tests', response_model=AlertTestPage)
def list_attempts(filters: Annotated[AlertTestFilters, Query()], session: SessionDependency) -> AlertTestPage:
    return alert_tests.list_attempts(session, filters)


@router.get('/alert-tests/{id}', response_model=AlertTestRead)
def get(id: Identifier, session: SessionDependency) -> AlertTestRead:
    return alert_tests.get(session, id)

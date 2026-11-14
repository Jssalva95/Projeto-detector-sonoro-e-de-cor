"""Additive dashboard endpoints for all active user roles, access JWT only."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_session, require_roles
from app.models.enums import Role
from app.schemas.dashboard import (
    DashboardSummary, EventsByPeriod, MachineStatusFilters, MachineStatusPage, PeriodFilters,
)
from app.services import dashboard

router = APIRouter(prefix='/api/v1/dashboard', tags=['Dashboard'],
                   dependencies=[Depends(require_roles(Role.ADMIN, Role.OPERATOR, Role.VIEWER))])
SessionDependency = Annotated[Session, Depends(get_session)]


@router.get('/summary', response_model=DashboardSummary)
def summary(session: SessionDependency) -> DashboardSummary:
    return dashboard.summary(session)


@router.get('/events-by-period', response_model=EventsByPeriod)
def events_by_period(filters: Annotated[PeriodFilters, Query()], session: SessionDependency) -> EventsByPeriod:
    return dashboard.events_by_period(session, filters)


@router.get('/machine-status', response_model=MachineStatusPage)
def machine_status(filters: Annotated[MachineStatusFilters, Query()], session: SessionDependency) -> MachineStatusPage:
    return dashboard.machine_status(session, filters)

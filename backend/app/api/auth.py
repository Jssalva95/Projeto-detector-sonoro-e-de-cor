"""Only the three authentication endpoints defined in the master specification."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.dependencies import current_user, get_auth_settings, get_session, unauthorized
from app.models import User
from app.schemas.auth import AuthErrorResponse, AccessTokenResponse, LoginRequest, RefreshRequest, TokenResponse
from app.schemas.domain import UserRead
from app.security import AuthSettings, InvalidCredentials
from app.services import auth

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"], responses={
    401: {"model": AuthErrorResponse, "description": "Invalid credentials"},
    422: {"model": AuthErrorResponse, "description": "Invalid authentication payload"},
    503: {"model": AuthErrorResponse, "description": "Authentication or database unavailable"},
})
SessionDependency = Annotated[Session, Depends(get_session)]
SettingsDependency = Annotated[AuthSettings, Depends(get_auth_settings)]


def no_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


@router.post("/login", response_model=TokenResponse, responses={401: {"description": "Invalid credentials"}})
def login(payload: LoginRequest, response: Response, session: SessionDependency,
          settings: SettingsDependency) -> TokenResponse:
    no_cache(response)
    try:
        return auth.login(session, payload.email, payload.password.get_secret_value(), settings)
    except InvalidCredentials:
        raise unauthorized() from None


@router.post("/refresh", response_model=AccessTokenResponse, responses={401: {"description": "Invalid credentials"}})
def refresh(payload: RefreshRequest, response: Response, session: SessionDependency,
            settings: SettingsDependency) -> AccessTokenResponse:
    no_cache(response)
    try:
        return auth.refresh(session, payload.refresh_token.get_secret_value(), settings)
    except InvalidCredentials:
        raise unauthorized() from None


@router.get("/me", response_model=UserRead, responses={401: {"description": "Invalid credentials"}})
def me(response: Response, user: Annotated[User, Depends(current_user)]) -> UserRead:
    no_cache(response)
    return UserRead.model_validate(user)

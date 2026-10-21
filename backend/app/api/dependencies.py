"""Request-scoped sessions and reusable access-token/RBAC dependencies."""

from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.session import DatabaseConfigurationError, session_scope
from app.models import User
from app.models.enums import Role
from app.security import AuthConfigurationError, AuthSettings, InvalidCredentials, auth_settings
from app.services.auth import authenticated_user

bearer = HTTPBearer(auto_error=False)


def get_session() -> Iterator[Session]:
    try:
        with session_scope() as session:
            yield session
    except (SQLAlchemyError, DatabaseConfigurationError):
        raise HTTPException(503, "Database unavailable") from None


def get_auth_settings() -> AuthSettings:
    try:
        return auth_settings()
    except AuthConfigurationError:
        raise HTTPException(503, "Authentication configuration unavailable") from None


def unauthorized() -> HTTPException:
    return HTTPException(401, "Invalid credentials", headers={"WWW-Authenticate": "Bearer"})


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
) -> User:
    if credentials is None:
        raise unauthorized()
    try:
        return authenticated_user(session, credentials.credentials, "access", settings)
    except InvalidCredentials:
        raise unauthorized() from None


def require_roles(*roles: Role) -> Callable[..., User]:
    """Explicit allowlist evaluated against the current persisted role."""
    def permitted(user: Annotated[User, Depends(current_user)]) -> User:
        if user.role not in roles:
            raise HTTPException(403, "Insufficient permissions")
        return user
    return permitted

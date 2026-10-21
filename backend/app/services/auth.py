"""Authentication policies; no registration endpoint or future permissions."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import User
from app.models.enums import Role
from app.repositories import users
from app.schemas.auth import AccessTokenResponse, TokenResponse
from app.security import (
    AuthSettings, InvalidCredentials, TokenType, dummy_hash, hash_password,
    issue_token, token_subject, verify_password,
)


class UserAlreadyExists(ValueError):
    pass


def authenticated_user(session: Session, token: str, purpose: TokenType,
                       settings: AuthSettings) -> User:
    user = users.by_id(session, token_subject(token, purpose, settings))
    if user is None or not user.is_active:
        raise InvalidCredentials("Invalid credentials")
    return user


def login(session: Session, email: str, password: str, settings: AuthSettings) -> TokenResponse:
    user = users.by_email(session, email)
    valid = verify_password(password, user.password_hash if user is not None else dummy_hash())
    if user is None or not user.is_active or not valid:
        raise InvalidCredentials("Invalid credentials")
    return TokenResponse(
        access_token=issue_token(user.id, "access", settings),
        refresh_token=issue_token(user.id, "refresh", settings),
        expires_in=settings.access_minutes * 60,
    )


def refresh(session: Session, token: str, settings: AuthSettings) -> AccessTokenResponse:
    user = authenticated_user(session, token, "refresh", settings)
    return AccessTokenResponse(
        access_token=issue_token(user.id, "access", settings),
        expires_in=settings.access_minutes * 60,
    )


def create_admin(session: Session, name: str, email: str, password: str) -> User:
    if users.by_email(session, email) is not None:
        raise UserAlreadyExists("User already exists; nothing changed")
    user = User(name=name, email=email, password_hash=hash_password(password),
                role=Role.ADMIN.value, is_active=True)
    try:
        with session.begin_nested():
            session.add(user)
            session.flush()
    except IntegrityError as error:
        if getattr(error.orig, "sqlstate", None) == "23505":
            raise UserAlreadyExists("User already exists; nothing changed") from None
        raise
    return user

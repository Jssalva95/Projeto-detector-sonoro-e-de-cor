"""Password hashing and explicitly configured, purpose-bound JWTs."""

import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Literal

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

TokenType = Literal["access", "refresh"]
password_hasher = PasswordHash.recommended()


class AuthConfigurationError(ValueError):
    """Configuration errors must not include environment values."""


class InvalidCredentials(ValueError):
    pass


@dataclass(frozen=True)
class AuthSettings:
    secret: str = field(repr=False)
    algorithm: str
    access_minutes: int
    refresh_minutes: int


def auth_settings() -> AuthSettings:
    names = ("JWT_SECRET", "JWT_ALGORITHM", "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
             "JWT_REFRESH_TOKEN_EXPIRE_MINUTES")
    values = [os.environ.get(name, "") for name in names]
    if not all(value.strip() for value in values):
        raise AuthConfigurationError("JWT configuration is required")
    secret, algorithm, access, refresh = values
    # A shared secret supports HMAC; never select an algorithm from a JWT header.
    minimum_bytes = {"HS256": 32, "HS384": 48, "HS512": 64}
    if algorithm not in minimum_bytes or len(secret.encode()) < minimum_bytes[algorithm]:
        raise AuthConfigurationError("Unsupported JWT algorithm or insufficient key length")
    try:
        durations = (int(access), int(refresh))
        now = datetime.now(timezone.utc)
        for minutes in durations:
            if minutes <= 0:
                raise ValueError
            now + timedelta(minutes=minutes)
    except (ValueError, OverflowError):
        raise AuthConfigurationError("JWT durations must be positive supported minutes") from None
    return AuthSettings(secret, algorithm, *durations)


@lru_cache(maxsize=1)
def dummy_hash() -> str:
    """Perform password work even for unknown accounts without a default password."""
    return password_hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return password_hasher.verify(password, hashed)
    except (UnknownHashError, ValueError):
        return False


def issue_token(user_id: int, token_type: TokenType, settings: AuthSettings) -> str:
    now = datetime.now(timezone.utc)
    minutes = settings.access_minutes if token_type == "access" else settings.refresh_minutes
    return jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=minutes),
         "token_type": token_type}, settings.secret, algorithm=settings.algorithm,
    )


def token_subject(token: str, expected_type: TokenType, settings: AuthSettings) -> int:
    try:
        payload = jwt.decode(
            token, settings.secret, algorithms=[settings.algorithm],
            options={"require": ["sub", "iat", "exp", "token_type"]},
        )
        subject = payload["sub"]
        if (payload["token_type"] != expected_type or not isinstance(subject, str)
                or not subject.isascii() or not subject.isdecimal() or len(subject) > 19):
            raise InvalidCredentials
        user_id = int(subject)
        if not 0 < user_id <= 9223372036854775807 or str(user_id) != subject:
            raise InvalidCredentials
        if (type(payload["iat"]) is not int or type(payload["exp"]) is not int
                or payload["exp"] <= payload["iat"]):
            raise InvalidCredentials
        return user_id
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError):
        raise InvalidCredentials("Invalid credentials") from None

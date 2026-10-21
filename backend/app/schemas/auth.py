"""Authentication inputs are distinct from internal persistence contracts."""

from typing import Literal

from pydantic import Field, SecretStr, field_validator

from app.schemas.domain import DataSchema


class LoginRequest(DataSchema):
    email: str = Field(min_length=1)
    password: SecretStr

    @field_validator("password")
    @classmethod
    def nonempty_password(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value():
            raise ValueError("Password is required")
        return value


class RefreshRequest(DataSchema):
    refresh_token: SecretStr


class AuthErrorResponse(DataSchema):
    detail: str


class AccessTokenResponse(DataSchema):
    access_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class TokenResponse(AccessTokenResponse):
    refresh_token: str = Field(repr=False)

"""Short database sessions; never keep tokens or ORM sessions on connections."""

from dataclasses import dataclass
import time

from app.database.session import session_scope
from app.models.enums import Role
from app.repositories.users import by_id
from app.security import InvalidCredentials, auth_settings, token_identity


class ForbiddenUser(ValueError):
    pass


@dataclass(frozen=True)
class Principal:
    user_id: int
    expires_at: int


def revalidate(principal: Principal) -> None:
    if principal.expires_at <= time.time():
        raise InvalidCredentials('Invalid credentials')
    with session_scope() as session:
        user = by_id(session, principal.user_id)
        if user is None or not user.is_active:
            raise InvalidCredentials('Invalid credentials')
        if user.role not in (Role.ADMIN, Role.OPERATOR, Role.VIEWER):
            raise ForbiddenUser('Insufficient permissions')


def authenticate(token: str) -> Principal:
    user_id, expiry = token_identity(token, 'access', auth_settings())
    principal = Principal(user_id, expiry)
    revalidate(principal)
    return principal

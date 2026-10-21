"""User queries reuse the approved case-insensitive email identity."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import User


def by_email(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(func.lower(User.email) == func.lower(email)))


def by_id(session: Session, user_id: int) -> User | None:
    return session.get(User, user_id)

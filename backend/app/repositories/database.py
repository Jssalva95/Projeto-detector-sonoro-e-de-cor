"""Database availability query."""

from sqlalchemy import text
from sqlalchemy.orm import Session


def database_responds(session: Session) -> bool:
    return session.scalar(text("SELECT 1")) == 1

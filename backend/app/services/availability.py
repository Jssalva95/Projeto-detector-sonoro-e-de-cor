"""Readiness policy preserving the bootstrap's failure response."""

from sqlalchemy.exc import SQLAlchemyError

from app.database.session import DatabaseConfigurationError, session_scope
from app.repositories.database import database_responds


def database_available() -> bool:
    try:
        with session_scope() as session:
            return database_responds(session)
    except (DatabaseConfigurationError, SQLAlchemyError):
        return False

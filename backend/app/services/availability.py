"""Readiness policy preserving the bootstrap's failure response."""

from pathlib import Path

from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy.exc import SQLAlchemyError

from app.database.session import DatabaseConfigurationError, session_scope
from app.repositories.database import database_responds

MIGRATION_DIRECTORY = Path(__file__).resolve().parents[2] / "alembic"


def database_available() -> bool:
    try:
        # Resolve the image's expected revisions without executing env.py or DDL.
        expected_heads = frozenset(ScriptDirectory(str(MIGRATION_DIRECTORY)).get_heads())
        with session_scope() as session:
            return database_responds(session, expected_heads)
    except (DatabaseConfigurationError, SQLAlchemyError, CommandError, OSError):
        return False

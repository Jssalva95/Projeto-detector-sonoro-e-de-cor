"""Read-only readiness probes using the application's mapped structure."""

from sqlalchemy import false, select, text
from sqlalchemy.orm import Session

from app.models import Base


def database_responds(session: Session, expected_heads: frozenset[str]) -> bool:
    if not expected_heads:
        return False
    applied_heads = frozenset(session.scalars(text("SELECT version_num FROM alembic_version")))
    if applied_heads != expected_heads:
        return False
    for table in Base.metadata.sorted_tables:
        # Resolve every mapped column and SELECT permission without reading rows.
        # A version stamp alone cannot prove that the required structure exists.
        session.execute(select(table).where(false())).close()
    return True

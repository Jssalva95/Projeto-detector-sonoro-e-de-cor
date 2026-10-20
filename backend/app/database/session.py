"""PostgreSQL engine and explicit transactional session lifecycle."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session


class DatabaseConfigurationError(ValueError):
    """Invalid or absent database configuration, without exposing credentials."""


def database_url() -> URL:
    raw = os.environ.get("DATABASE_URL")
    if not raw:
        raise DatabaseConfigurationError("DATABASE_URL is required")
    try:
        url = make_url(raw)
    except (ArgumentError, ValueError):
        raise DatabaseConfigurationError("Invalid DATABASE_URL") from None
    if url.drivername not in {"postgresql", "postgresql+psycopg"}:
        raise DatabaseConfigurationError("PostgreSQL with psycopg is required")
    return url.set(drivername="postgresql+psycopg")


@lru_cache(maxsize=1)
def _engine(url: URL) -> Engine:
    return create_engine(url, pool_pre_ping=True, hide_parameters=True)


def get_engine() -> Engine:
    return _engine(database_url())


@contextmanager
def session_scope(bind: Engine | None = None) -> Iterator[Session]:
    """Commit on success, rollback on failure, and always release the session."""
    with Session(bind or get_engine(), expire_on_commit=False) as session:
        with session.begin():
            yield session

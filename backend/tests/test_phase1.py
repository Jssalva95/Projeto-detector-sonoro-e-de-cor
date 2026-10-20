"""Infrastructure tests; the temporary probe is not a domain model."""

import os
from collections.abc import Iterator

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import Column, Engine, Integer, Text, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool

from app.database.session import DatabaseConfigurationError, database_url, session_scope
from app.main import app


class ProbeBase(DeclarativeBase):
    pass


class PersistenceProbe(ProbeBase):
    __tablename__ = "phase1_probe"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[str] = mapped_column(Text)


@pytest.fixture
def probe_engine() -> Iterator[Engine]:
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("Requires PostgreSQL")
    # One private connection, so the temporary table is never shared with the API.
    engine = create_engine(database_url(), poolclass=StaticPool, hide_parameters=True)
    try:
        with engine.begin() as connection:
            operations = Operations(MigrationContext.configure(connection))
            operations.create_table(
                "phase1_probe",
                Column("id", Integer, primary_key=True),
                Column("value", Text, nullable=False),
                prefixes=["TEMPORARY"],
                postgresql_on_commit="PRESERVE ROWS",
            )
        yield engine
    finally:
        # Closing the physical connection removes its pg_temp table, even on failure.
        engine.dispose()


def test_postgresql_url_preserves_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://fixture:p%40ss%25@postgres/sample")
    url = database_url()
    assert url.drivername == "postgresql+psycopg"
    assert url.password == "p@ss%"
    assert url.database == "sample"


@pytest.mark.parametrize("value", ["invalid-secret", "sqlite:///fixture.db"])
def test_invalid_configuration_is_safe(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("DATABASE_URL", value)
    with pytest.raises(DatabaseConfigurationError) as error:
        database_url()
    assert value not in str(error.value)
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/ready").status_code == 503


def test_docs_and_health_contract() -> None:
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 200
        schema = client.get("/openapi.json").json()
        assert set(schema["paths"]) == {"/health", "/ready"}
        assert schema["components"]["schemas"]["HealthResponse"]["properties"]["status"]["const"] == "ok"


def test_orm_commit_and_reload(probe_engine: Engine) -> None:
    with session_scope(probe_engine) as session:
        session.add(PersistenceProbe(id=1, value="test fixture only"))
    with session_scope(probe_engine) as session:
        row = session.get(PersistenceProbe, 1)
        assert row is not None
        assert row.value == "test fixture only"


def test_rollback_and_session_reuse(probe_engine: Engine) -> None:
    with pytest.raises(RuntimeError, match="abort fixture"):
        with session_scope(probe_engine) as session:
            session.add(PersistenceProbe(id=2, value="must roll back"))
            session.flush()
            raise RuntimeError("abort fixture")
    with session_scope(probe_engine) as session:
        assert session.get(PersistenceProbe, 2) is None
        session.add(PersistenceProbe(id=2, value="committed after rollback"))
    with pytest.raises(IntegrityError):
        with session_scope(probe_engine) as session:
            session.add(PersistenceProbe(id=2, value="duplicate"))
    with session_scope(probe_engine) as session:
        row = session.get(PersistenceProbe, 2)
        assert row is not None
        assert row.value == "committed after rollback"


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="Requires PostgreSQL")
def test_baseline_migration_applied() -> None:
    engine = create_engine(database_url(), hide_parameters=True)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0002_domain_models"
            columns = inspect(connection).get_columns("alembic_version")
            assert [column["name"] for column in columns] == ["version_num"]
    finally:
        engine.dispose()

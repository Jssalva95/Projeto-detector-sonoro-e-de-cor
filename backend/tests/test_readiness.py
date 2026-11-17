"""Readiness against isolated PostgreSQL schemas, with transactional DDL rollback."""

from contextlib import contextmanager

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import Column, String, event, text

from app.main import app
from app.models import Base
from app.services import availability
from test_domain import db, delivery_test_migration


@pytest.fixture
def ready_client(db, monkeypatch):
    operations = Operations(MigrationContext.configure(db.connection()))
    operations.create_table("alembic_version", Column("version_num", String(32), primary_key=True))
    db.execute(text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
               {"revision": delivery_test_migration().revision})

    @contextmanager
    def isolated_session():
        # Each failed SELECT rolls back its own savepoint, leaving the fixture usable.
        with db.begin_nested():
            yield db

    monkeypatch.setattr(availability, "session_scope", isolated_session)
    with TestClient(app) as client:
        yield client


def assert_unavailable(client):
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("table_name", sorted(Base.metadata.tables))
def test_missing_table_not_ready_then_recovers(ready_client, db, table_name):
    assert ready_client.get("/ready").status_code == 200
    # Names originate only from trusted metadata; no public table is modified.
    db.execute(text(f'ALTER TABLE "{table_name}" RENAME TO "readiness_missing"'))
    assert_unavailable(ready_client)
    db.execute(text(f'ALTER TABLE "readiness_missing" RENAME TO "{table_name}"'))
    assert ready_client.get("/ready").status_code == 200


@pytest.mark.parametrize("table_name, column_name", [
    ("devices", "status_event_id_floor"),
    ("alerts", "attempt_started_at"),
    ("alert_test_attempts", "destination"),
])
def test_missing_column_despite_current_revision(ready_client, db, table_name, column_name):
    db.execute(text(f'ALTER TABLE "{table_name}" RENAME COLUMN "{column_name}" TO "readiness_missing"'))
    assert_unavailable(ready_client)
    db.execute(text(f'ALTER TABLE "{table_name}" RENAME COLUMN "readiness_missing" TO "{column_name}"'))
    assert ready_client.get("/ready").status_code == 200


@pytest.mark.parametrize("revisions", [[], ["0004_device_status_context"], ["unknown_revision"],
                                       ["0005_alert_test_attempts", "unexpected_branch"]])
def test_revision_mismatch_then_recovers(ready_client, db, revisions):
    db.execute(text("DELETE FROM alembic_version"))
    for revision in revisions:
        db.execute(text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": revision})
    assert_unavailable(ready_client)
    db.execute(text("DELETE FROM alembic_version"))
    db.execute(text("INSERT INTO alembic_version VALUES (:revision)"),
               {"revision": delivery_test_migration().revision})
    assert ready_client.get("/ready").status_code == 200


def test_missing_migration_table(ready_client, db):
    db.execute(text("ALTER TABLE alembic_version RENAME TO readiness_missing"))
    assert_unavailable(ready_client)


@pytest.mark.parametrize("exists", [False, True])
def test_missing_or_empty_packaged_migrations(ready_client, monkeypatch, tmp_path, exists):
    directory = tmp_path / "migrations"
    if exists:
        directory.mkdir()
    monkeypatch.setattr(availability, "MIGRATION_DIRECTORY", directory)
    assert_unavailable(ready_client)


def test_migration_path_independent_of_working_directory(ready_client, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert ready_client.get("/ready").status_code == 200


def test_empty_database_not_ready(ready_client, db):
    # Removing names inside the private schema cannot fall back to public tables:
    # test_domain.db sets search_path exclusively to that private schema.
    for table_name in Base.metadata.tables:
        db.execute(text(f'ALTER TABLE "{table_name}" RENAME TO "missing_{table_name}"'))
    db.execute(text("ALTER TABLE alembic_version RENAME TO missing_alembic_version"))
    assert_unavailable(ready_client)


def test_ready_only_issues_reads_and_does_not_fetch_domain_rows(ready_client, db):
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    connection = db.connection()
    event.listen(connection, "before_cursor_execute", capture)
    try:
        response = ready_client.get("/ready")
    finally:
        event.remove(connection, "before_cursor_execute", capture)
    assert response.status_code == 200 and response.json() == {"status": "ok"}
    assert all(sql.lstrip().upper().startswith(("SELECT", "SAVEPOINT", "RELEASE SAVEPOINT"))
               for sql in statements)
    # A false predicate resolves all mapped columns without retrieving records.
    domain_reads = [sql for sql in statements if "WHERE false" in sql]
    assert len(domain_reads) == len(Base.metadata.tables)

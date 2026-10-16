import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.database.connection import check_database
from app.main import app


def test_connection_failure_is_unavailable(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")

    def fail(*args, **kwargs):
        raise psycopg.OperationalError("sensitive connection details")

    monkeypatch.setattr(psycopg, "connect", fail)
    with TestClient(app) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert "sensitive" not in response.text


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="Requires PostgreSQL")
def test_real_postgresql_connection():
    assert check_database()
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 200

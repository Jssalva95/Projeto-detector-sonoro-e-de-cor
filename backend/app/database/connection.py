"""Connectivity only: no schema or domain models in phase 0."""

import os

import psycopg


def check_database() -> bool:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return False
    try:
        with psycopg.connect(database_url) as connection:
            return connection.execute("SELECT 1").fetchone() == (1,)
    except psycopg.Error:
        return False

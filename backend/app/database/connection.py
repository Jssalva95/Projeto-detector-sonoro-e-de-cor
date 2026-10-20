"""Compatibility entry point for the existing bootstrap health checks."""

from app.services.availability import database_available


def check_database() -> bool:
    return database_available()

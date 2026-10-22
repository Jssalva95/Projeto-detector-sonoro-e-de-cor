"""Bound SQL queries with deterministic ordering and database pagination."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SensorReading
from app.schemas.readings import ReadingFilters


def by_id(session: Session, identifier: int) -> SensorReading | None:
    return session.get(SensorReading, identifier)


def list_readings(session: Session, filters: ReadingFilters) -> list[SensorReading]:
    statement = select(SensorReading)
    if filters.machine_id is not None:
        statement = statement.where(SensorReading.machine_id == filters.machine_id)
    if filters.start_date is not None:
        statement = statement.where(SensorReading.timestamp >= filters.start_date)
    if filters.end_date is not None:
        statement = statement.where(SensorReading.timestamp <= filters.end_date)
    if filters.color is not None:
        statement = statement.where(SensorReading.color == filters.color)
    if filters.sound_detected is not None:
        statement = statement.where(SensorReading.sound_detected == filters.sound_detected)
    statement = statement.order_by(SensorReading.timestamp.desc(), SensorReading.id.desc())
    return list(session.scalars(statement.limit(filters.limit).offset(filters.offset)))

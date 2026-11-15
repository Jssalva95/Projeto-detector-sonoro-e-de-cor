"""Register every approved model for Alembic metadata discovery."""

from app.models.base import Base
from app.models.domain import Alert, AlertRecipient, Device, Event, Machine, SensorReading, User
from app.models.alert_tests import AlertTestAttempt

__all__ = ["Base", "User", "Machine", "Device", "SensorReading", "Event", "AlertRecipient", "Alert", "AlertTestAttempt"]

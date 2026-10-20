"""Values specified in PROJECT_MASTER_PROMPT.md; stored as TEXT + CHECK."""

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"


class MachineStatus(StrEnum):
    NORMAL = "NORMAL"
    FAULT = "FAULT"
    OFFLINE = "OFFLINE"
    MAINTENANCE = "MAINTENANCE"


class Color(StrEnum):
    BLUE = "BLUE"
    RED = "RED"
    UNKNOWN = "UNKNOWN"


class EventType(StrEnum):
    COLOR_RED = "COLOR_RED"
    ALARM_SOUND = "ALARM_SOUND"
    FAULT_CONFIRMED = "FAULT_CONFIRMED"
    FAULT_RECOVERED = "FAULT_RECOVERED"
    DEVICE_OFFLINE = "DEVICE_OFFLINE"
    DEVICE_ONLINE = "DEVICE_ONLINE"


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class Channel(StrEnum):
    TELEGRAM = "TELEGRAM"
    EMAIL = "EMAIL"
    WHATSAPP = "WHATSAPP"
    SMS = "SMS"


class AlertStatus(StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"

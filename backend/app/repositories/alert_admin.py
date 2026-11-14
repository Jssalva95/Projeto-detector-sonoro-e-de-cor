"""Administrative reads and recipient locks shared by every attempt writer."""

from sqlalchemy import Select, func, select, true
from sqlalchemy.orm import Session

from app.models import Alert, AlertRecipient, Event


def recipient(session: Session, identifier: int, *, lock: bool = False) -> AlertRecipient | None:
    statement = select(AlertRecipient).where(AlertRecipient.id == identifier)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return session.scalar(statement)


def has_attempts(session: Session, identifier: int) -> bool:
    # Stage 5 must extend this guard to alert_test_attempts when that table exists.
    return session.scalar(select(Alert.id).where(Alert.recipient_id == identifier).limit(1)) is not None


def page(session: Session, model: type[Alert] | type[AlertRecipient], statement: Select,
         limit: int, offset: int, *, descending: bool = False) -> tuple[int, list[dict[str, object]]]:
    """Count and page use one snapshot, including offsets beyond the last row."""
    filtered = statement.cte('filtered')
    order = filtered.c.id.desc() if descending else filtered.c.id
    selected = select(filtered).order_by(order).limit(limit).offset(offset).cte('page')
    metadata = select(func.count().label('total')).select_from(filtered).cte('metadata')
    rows = session.execute(select(metadata, selected).select_from(metadata).outerjoin(
        selected, true()).order_by(selected.c.id.desc() if descending else selected.c.id)).mappings().all()
    keys = tuple(column.name for column in model.__table__.columns)
    return rows[0]['total'], [{key: row[key] for key in keys} for row in rows if row['id'] is not None]


def recipients(session: Session, channel: str | None, active: bool | None,
               limit: int, offset: int) -> tuple[int, list[dict[str, object]]]:
    statement = select(AlertRecipient)
    if channel is not None:
        statement = statement.where(AlertRecipient.channel == channel)
    if active is not None:
        statement = statement.where(AlertRecipient.is_active == active)
    return page(session, AlertRecipient, statement, limit, offset)


def alerts(session: Session, filters: dict[str, object], limit: int, offset: int) -> tuple[int, list[dict[str, object]]]:
    statement = select(Alert).join(Event, Event.id == Alert.event_id)
    for key, value in filters.items():
        if value is not None:
            column = Event.machine_id if key == 'machine_id' else getattr(Alert, key)
            statement = statement.where(column == value)
    return page(session, Alert, statement, limit, offset, descending=True)

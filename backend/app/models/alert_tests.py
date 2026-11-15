"""Approved independent test-delivery history; never linked to a real event."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Text, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.domain import AlertRecipient, IdentityCreated, User, reference


class AlertTestAttempt(IdentityCreated, Base):
    __tablename__ = 'alert_test_attempts'
    __table_args__ = (
        UniqueConstraint('uuid', name='uq_alert_test_attempts_uuid'),
        CheckConstraint("channel IN ('EMAIL', 'TELEGRAM')", name='ck_alert_test_attempts_channel'),
        CheckConstraint("status IN ('PENDING', 'SENT', 'FAILED')", name='ck_alert_test_attempts_status'),
        CheckConstraint(
            "(status = 'PENDING' AND sent_at IS NULL AND error_message IS NULL) OR "
            "(status = 'SENT' AND attempt_started_at IS NOT NULL AND sent_at IS NOT NULL AND error_message IS NULL) OR "
            "(status = 'FAILED' AND attempt_started_at IS NOT NULL AND sent_at IS NULL "
            "AND error_message IS NOT NULL AND error_message <> '')", name='ck_alert_test_attempts_outcome'),
        CheckConstraint('attempt_started_at >= created_at', name='ck_alert_test_attempts_start_order'),
        CheckConstraint('sent_at >= attempt_started_at', name='ck_alert_test_attempts_sent_order'),
        Index('ix_alert_test_attempts_status_id', 'status', 'id'),
        Index('uq_alert_test_attempts_pending_recipient', 'recipient_id', unique=True,
              postgresql_where=text("status = 'PENDING'")),
    )

    uuid: Mapped[UUID] = mapped_column(Uuid)
    recipient_id: Mapped[int] = mapped_column(BigInteger, reference('alert_recipients.id'), index=True)
    requested_by: Mapped[int] = mapped_column(BigInteger, reference('users.id'), index=True)
    channel: Mapped[str] = mapped_column(Text)
    destination: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    attempt_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    recipient: Mapped[AlertRecipient] = relationship(back_populates='test_attempts')
    requester: Mapped[User] = relationship(back_populates='test_attempts')

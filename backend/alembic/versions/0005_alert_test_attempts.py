"""Independent, durable test-send queue. No changes to real alerts.

Revision ID: 0005_alert_test_attempts
Revises: 0004_device_status_context
"""
from alembic import op
import sqlalchemy as sa

revision = '0005_alert_test_attempts'
down_revision = '0004_device_status_context'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'alert_test_attempts',
        sa.Column('id', sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column('uuid', sa.Uuid(), nullable=False),
        sa.Column('recipient_id', sa.BigInteger(), sa.ForeignKey('alert_recipients.id', ondelete='RESTRICT', onupdate='RESTRICT'), nullable=False),
        sa.Column('requested_by', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='RESTRICT', onupdate='RESTRICT'), nullable=False),
        sa.Column('channel', sa.Text(), nullable=False),
        sa.Column('destination', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('attempt_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.UniqueConstraint('uuid', name='uq_alert_test_attempts_uuid'),
        sa.CheckConstraint("channel IN ('EMAIL', 'TELEGRAM')", name='ck_alert_test_attempts_channel'),
        sa.CheckConstraint("status IN ('PENDING', 'SENT', 'FAILED')", name='ck_alert_test_attempts_status'),
        sa.CheckConstraint(
            "(status = 'PENDING' AND sent_at IS NULL AND error_message IS NULL) OR "
            "(status = 'SENT' AND attempt_started_at IS NOT NULL AND sent_at IS NOT NULL AND error_message IS NULL) OR "
            "(status = 'FAILED' AND attempt_started_at IS NOT NULL AND sent_at IS NULL "
            "AND error_message IS NOT NULL AND error_message <> '')", name='ck_alert_test_attempts_outcome'),
        sa.CheckConstraint('attempt_started_at >= created_at', name='ck_alert_test_attempts_start_order'),
        sa.CheckConstraint('sent_at >= attempt_started_at', name='ck_alert_test_attempts_sent_order'),
    )
    op.create_index('ix_alert_test_attempts_recipient_id', 'alert_test_attempts', ['recipient_id'])
    op.create_index('ix_alert_test_attempts_requested_by', 'alert_test_attempts', ['requested_by'])
    op.create_index('ix_alert_test_attempts_status_id', 'alert_test_attempts', ['status', 'id'])
    op.create_index('uq_alert_test_attempts_pending_recipient', 'alert_test_attempts', ['recipient_id'],
                    unique=True, postgresql_where=sa.text("status = 'PENDING'"))


def downgrade() -> None:
    # Isolated tests only: dropping this table discards reservations/history.
    op.drop_table('alert_test_attempts')

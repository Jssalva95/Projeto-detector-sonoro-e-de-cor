"""Invalidate connectivity evidence preceding the current device context.

Revision ID: 0004_device_status_context
Revises: 0003_alert_attempts
"""
from alembic import op
import sqlalchemy as sa

revision = '0004_device_status_context'
down_revision = '0003_alert_attempts'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing ingestion takes a device lock before inserting an event. Acquire
    # the device table first, then block event writers for the whole backfill.
    op.execute('LOCK TABLE devices IN ACCESS EXCLUSIVE MODE')
    op.execute('LOCK TABLE events IN SHARE ROW EXCLUSIVE MODE')
    op.add_column('devices', sa.Column('status_event_id_floor', sa.BigInteger(),
                                      nullable=False, server_default=sa.text('0')))
    op.execute('''UPDATE devices AS d SET status_event_id_floor = previous.event_id
                  FROM (SELECT device_id, max(id) AS event_id FROM events GROUP BY device_id) AS previous
                  WHERE previous.device_id = d.id''')
    op.create_check_constraint('ck_devices_status_event_id_floor', 'devices', 'status_event_id_floor >= 0')


def downgrade() -> None:
    # For isolated tests only: dropping the boundary loses context history.
    op.drop_constraint('ck_devices_status_event_id_floor', 'devices', type_='check')
    op.drop_column('devices', 'status_event_id_floor')

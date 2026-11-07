"""Durable reservation before external delivery.

Revision ID: 0003_alert_attempts
Revises: 0002_domain_models
"""
from alembic import op
import sqlalchemy as sa

revision = '0003_alert_attempts'
down_revision = '0002_domain_models'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('alerts', sa.Column('attempt_started_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('alerts', 'attempt_started_at')

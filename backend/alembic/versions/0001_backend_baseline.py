"""Establish the migration baseline without assuming domain modeling decisions.

Only Alembic's version bookkeeping is created. Domain DDL awaits approval of
docs/database-proposal.md and must be introduced by a subsequent revision.
"""

revision = "0001_backend_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

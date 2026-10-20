"""Read credentials from the environment; never store a URL in alembic.ini."""

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.database.session import database_url
from app.models import Base


def offline() -> None:
    context.configure(
        url=database_url(), target_metadata=Base.metadata,
        literal_binds=True, dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def online() -> None:
    engine = create_engine(database_url(), poolclass=NullPool, hide_parameters=True)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=Base.metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    offline()
else:
    online()

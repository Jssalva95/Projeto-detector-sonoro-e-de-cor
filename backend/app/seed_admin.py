"""Manual command: python -m app.seed_admin. Never executed at startup."""

import os

from sqlalchemy.exc import SQLAlchemyError

from app.database.session import DatabaseConfigurationError, session_scope
from app.services.auth import UserAlreadyExists, create_admin


def main() -> int:
    values = [os.environ.get(key, "") for key in ("ADMIN_NAME", "ADMIN_EMAIL", "ADMIN_PASSWORD")]
    if not all(value.strip() for value in values):
        print("ADMIN_NAME, ADMIN_EMAIL and ADMIN_PASSWORD are required; nothing changed.")
        return 1
    try:
        with session_scope() as session:
            create_admin(session, *values)
    except UserAlreadyExists:
        print("User already exists; nothing changed.")
        return 1
    except (SQLAlchemyError, DatabaseConfigurationError):
        print("Database unavailable or operation rejected; nothing committed.")
        return 1
    print("Administrator created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

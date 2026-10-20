"""Shared declarative registry. Tables are managed exclusively by Alembic."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass

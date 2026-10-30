"""SQLAlchemy engine, sessions and transaction dependency."""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings


@lru_cache(maxsize=1)
def get_engine(dsn: str):
    return create_engine(dsn, pool_pre_ping=True, pool_recycle=1800, future=True)


def get_session_factory(settings: Settings | None = None):
    active = settings or get_settings()
    return sessionmaker(bind=get_engine(active.mysql_dsn), autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def transactional_session(settings: Settings | None = None) -> Iterator[Session]:
    session = get_session_factory(settings)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

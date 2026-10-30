"""SQLAlchemy engine, sessions and transaction dependency."""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
import time
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.telemetry import record_sample


@lru_cache(maxsize=1)
def get_engine(dsn: str):
    engine = create_engine(dsn, pool_pre_ping=True, pool_recycle=1800, future=True)

    @event.listens_for(engine, "before_cursor_execute")
    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        context._chargeops_started = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        started = getattr(context, "_chargeops_started", None)
        if started is not None:
            record_sample("database", (time.perf_counter() - started) * 1000, "success")

    @event.listens_for(engine, "handle_error")
    def _handle_error(exception_context):
        context = exception_context.execution_context
        started = getattr(context, "_chargeops_started", None) if context is not None else None
        if started is not None:
            record_sample("database", (time.perf_counter() - started) * 1000, "error")

    return engine


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

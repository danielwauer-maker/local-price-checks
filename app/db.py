from contextvars import ContextVar, Token

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, URL
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import database_url


_request_query_metrics: ContextVar[dict[str, int] | None] = ContextVar(
    "spareno_request_query_metrics", default=None
)


def begin_request_query_metrics() -> tuple[dict[str, int], Token]:
    metrics = {"queries": 0}
    return metrics, _request_query_metrics.set(metrics)


def end_request_query_metrics(token: Token) -> None:
    _request_query_metrics.reset(token)


def _count_request_query(*_args) -> None:
    metrics = _request_query_metrics.get()
    if metrics is not None:
        metrics["queries"] += 1


def create_database_engine(url: str | URL | None = None) -> Engine:
    parsed = database_url(str(url) if url is not None else None)
    connect_args = {"check_same_thread": False, "timeout": 30} if parsed.get_backend_name() == "sqlite" else {}
    configured_engine = create_engine(parsed, connect_args=connect_args, future=True, pool_pre_ping=True)
    event.listen(configured_engine, "before_cursor_execute", _count_request_query)

    if parsed.get_backend_name() == "sqlite":
        event.listen(configured_engine, "connect", _configure_sqlite)
    return configured_engine


def _configure_sqlite(dbapi_connection, connection_record):
    """Make SQLite resilient to concurrent web/API writes.

    WAL lets readers continue while another request writes. ``busy_timeout``
    gives short competing writes time to finish instead of immediately
    raising ``database is locked``. Foreign keys are enabled for every SQLite
    connection; PostgreSQL connections never use this hook.
    """

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
    finally:
        cursor.close()


engine = create_database_engine()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

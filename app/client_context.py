from __future__ import annotations

from contextvars import ContextVar

_client_key: ContextVar[str | None] = ContextVar("localprices_client_key", default=None)


def set_client_key(value: str | None):
    return _client_key.set(value)


def reset_client_key(token) -> None:
    _client_key.reset(token)


def get_client_key() -> str | None:
    return _client_key.get()

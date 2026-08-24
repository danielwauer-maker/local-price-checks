from __future__ import annotations

from contextvars import ContextVar

_client_key: ContextVar[str | None] = ContextVar("localprices_client_key", default=None)
_legacy_client_key: ContextVar[str | None] = ContextVar("localprices_legacy_client_key", default=None)
_request_method: ContextVar[str | None] = ContextVar("localprices_request_method", default=None)


def set_client_key(value: str | None):
    return _client_key.set(value)


def reset_client_key(token) -> None:
    _client_key.reset(token)


def get_client_key() -> str | None:
    return _client_key.get()


def set_legacy_client_key(value: str | None):
    return _legacy_client_key.set(value)


def reset_legacy_client_key(token) -> None:
    _legacy_client_key.reset(token)


def get_legacy_client_key() -> str | None:
    return _legacy_client_key.get()


def set_request_method(value: str | None):
    return _request_method.set((value or "").upper() or None)


def reset_request_method(token) -> None:
    _request_method.reset(token)


def get_request_method() -> str | None:
    return _request_method.get()

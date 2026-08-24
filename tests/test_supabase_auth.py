from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.supabase_auth as supabase_auth


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_verify_supabase_access_token_uses_auth_server(monkeypatch):
    monkeypatch.setattr(
        supabase_auth,
        "settings",
        SimpleNamespace(
            supabase_url="https://project.supabase.co",
            supabase_publishable_key="sb_publishable_test",
        ),
    )
    seen = {}

    def fake_get(url, headers, timeout):
        seen.update(url=url, headers=headers, timeout=timeout)
        return FakeResponse(200, {"id": "user-123", "email": "test@example.com"})

    monkeypatch.setattr(supabase_auth.httpx, "get", fake_get)
    user = supabase_auth.verify_supabase_access_token("access-token")

    assert user.user_id == "user-123"
    assert user.email == "test@example.com"
    assert seen["url"].endswith("/auth/v1/user")
    assert seen["headers"]["apikey"] == "sb_publishable_test"
    assert seen["headers"]["Authorization"] == "Bearer access-token"


def test_verify_supabase_access_token_rejects_invalid_session(monkeypatch):
    monkeypatch.setattr(
        supabase_auth,
        "settings",
        SimpleNamespace(
            supabase_url="https://project.supabase.co",
            supabase_publishable_key="sb_publishable_test",
        ),
    )
    monkeypatch.setattr(supabase_auth.httpx, "get", lambda *args, **kwargs: FakeResponse(401, {}))

    with pytest.raises(HTTPException) as exc:
        supabase_auth.verify_supabase_access_token("bad-token")
    assert exc.value.status_code == 401

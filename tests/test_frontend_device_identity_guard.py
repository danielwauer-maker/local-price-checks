from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "frontend-lovable-source" / "src"


def test_lokero_api_uses_same_origin_cookie_identity():
    api_client = (ROOT / "services" / "lokero-api.ts").read_text(encoding="utf-8")

    assert 'credentials: "include"' in api_client
    assert 'fetch(path' in api_client
    assert '"/api/' in api_client


def test_lokero_state_api_uses_same_origin_cookie_identity():
    state_client = (ROOT / "services" / "lokero-state-api.ts").read_text(encoding="utf-8")

    assert 'credentials: "include"' in state_client
    assert 'fetch(path' in state_client
    assert '/api/lokero/' in state_client

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "frontend-lovable-source" / "src"


def test_client_entry_installs_device_aware_api_fetch_before_pwa():
    client = (ROOT / "client.tsx").read_text(encoding="utf-8")
    api_import = 'import "./lib/api-client";'
    pwa_import = 'import "./pwa";'

    assert api_import in client
    assert pwa_import in client
    assert client.index(api_import) < client.index(pwa_import)


def test_api_client_protects_all_same_origin_api_fetches():
    api_client = (ROOT / "lib" / "api-client.ts").read_text(encoding="utf-8")

    assert 'url.pathname.startsWith("/api/")' in api_client
    assert "withDeviceIdentity" in api_client
    assert "window.fetch =" in api_client
    assert "installDeviceAwareApiFetch();" in api_client

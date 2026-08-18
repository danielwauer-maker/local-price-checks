import json
from dataclasses import replace
from types import SimpleNamespace

from app.admin_collector_routes import _write_lidl_debug_failure


def test_lidl_debug_failure_always_writes_json(monkeypatch, tmp_path):
    import app.admin_collector_routes as routes

    monkeypatch.setattr(routes, "settings", replace(routes.settings, data_dir=tmp_path))
    store = SimpleNamespace(id=8, name="Lidl Puderbach", retailer="Lidl", external_id=None)

    _write_lidl_debug_failure(store, RuntimeError("diagnostic boom"))

    target = tmp_path / "diagnostics" / "lidl" / "lidl_manifest_debug_store_8_latest.json"
    assert target.exists()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["payload_count"] == 0
    assert payload["stage"] == "diagnostic_setup"
    assert "RuntimeError: diagnostic boom" in payload["error"]

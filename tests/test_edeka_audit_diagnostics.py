import json

from app.edeka_web_offer_audit_orchestrator import _attach_source_breakdown


class _Run:
    comparison_json = "{}"


class _Db:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1

    def refresh(self, _run):
        return None


def test_admin_comparison_persists_safe_central_fetch_diagnostics():
    run = _Run()
    db = _Db()
    result = type("Result", (), {"artifacts": {
        "source_breakdown": {"central_count": 224, "local_count": 73},
        "central_fetch_method": "DOM_DIRECT",
        "central_fetch_http_status": 200,
        "central_fetch_http_version": "HTTP/1.1",
        "central_fetch_final_host": "www.edeka.de",
        "central_fetch_block_reason": None,
        "central_fetch_fallback_used": False,
        "central_structured_endpoint": None,
        "central_dom_count": 224,
        "central_parsed_count": 224,
        "central_reference_count": 224,
        "central_fetch_response_headers": {"content-type": "text/html; charset=utf-8"},
        "central_fetch_redirect_chain": [],
    }})()

    _attach_source_breakdown(db, run, result)

    comparison = json.loads(run.comparison_json)
    assert comparison["source_central_count"] == 224
    assert comparison["central_fetch_method"] == "DOM_DIRECT"
    assert comparison["central_fetch_http_status"] == 200
    assert comparison["central_fetch_final_host"] == "www.edeka.de"
    assert comparison["central_dom_count"] == 224
    assert comparison["central_parsed_count"] == 224
    assert comparison["central_reference_count"] == 224
    assert "set-cookie" not in comparison["central_fetch_response_headers"]
    assert db.commits == 1

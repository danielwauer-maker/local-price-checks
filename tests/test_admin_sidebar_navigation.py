from pathlib import Path


TEMPLATES = Path(__file__).resolve().parents[1] / "app" / "templates"


def test_admin_sidebar_contains_all_current_admin_features():
    sidebar = (TEMPLATES / "admin_sidebar.html").read_text(encoding="utf-8")
    expected_links = [
        "/admin?tab=dashboard",
        "/admin/datenstatus",
        "/admin/coverage",
        "/admin/coverage/coordinate-review",
        "/admin/market-identities",
        "/admin?tab=stores",
        "/admin/collector",
        "/admin/rollout",
        "/admin/web-offer-audit",
        "/admin/articles/prospect-audit",
        "/admin/articles/prospect-audit/errors",
        "/admin/quality/provenance",
        "/admin/collector/readiness",
        "/admin?tab=products",
        "/admin?tab=quality",
        "/admin?tab=categories",
        "/admin?tab=media",
        "/admin/product-media-review",
        "/admin/lokero-controls",
        "/admin/users",
        "/admin?tab=settings",
        "/admin?tab=audit",
        "/admin/support-export.zip",
    ]
    for link in expected_links:
        assert link in sidebar


def test_market_release_links_are_in_operator_workflow_order():
    sidebar = (TEMPLATES / "admin_sidebar.html").read_text(encoding="utf-8")
    workflow = [
        "/admin/coverage",
        "/admin/coverage/coordinate-review",
        "/admin/market-identities",
        "/admin?tab=stores",
        "/admin/collector",
        "/admin/rollout",
        "/admin/web-offer-audit",
        "/admin/articles/prospect-audit",
        "/admin/articles/prospect-audit/errors",
        "/admin/quality/provenance",
        "/admin/collector/readiness",
    ]
    positions = [sidebar.index(f'href="{link}"') for link in workflow]
    assert positions == sorted(positions)
    assert "Marktfreigabe in 5 Schritten" in sidebar
    assert "Gebiet → Identität → Collector → Qualität → Produktion" in sidebar


def test_all_admin_workspaces_use_shared_sidebar():
    expected_sections = {
        "admin.html": "admin_sidebar.html",
        "admin_collector.html": "admin_section = 'collector'",
        "admin_coverage.html": "admin_section = 'coverage'",
        "admin_candidate_coordinate_queue.html": "admin_section = 'coordinate_review'",
        "admin_candidate_coordinate_review.html": "admin_sidebar.html",
        "admin_market_identities.html": "admin_sidebar.html",
        "admin_rollout.html": "admin_section = 'rollout'",
        "admin_production_readiness.html": "admin_sidebar.html",
        "admin_product_media_review.html": "admin_section = 'product_media_review'",
        "admin_prospect_audit.html": "admin_section = 'prospect_audit'",
        "admin_web_offer_audit.html": "admin_section = 'web_offer_audit'",
        "admin_prospect_errors.html": "admin_sidebar.html",
        "admin_provenance.html": "admin_section = 'provenance'",
    }
    for filename, marker in expected_sections.items():
        content = (TEMPLATES / filename).read_text(encoding="utf-8")
        assert "admin_sidebar.html" in content
        assert marker in content


def test_release_pages_have_distinct_navigation_states_in_routes():
    root = TEMPLATES.parent
    candidate_routes = (root / "admin_candidate_coordinate_routes.py").read_text(encoding="utf-8")
    identity_routes = (root / "admin_market_identity_routes.py").read_text(encoding="utf-8")
    data_status_routes = (root / "admin_data_status_routes.py").read_text(encoding="utf-8")
    assert '"admin_section": "coordinate_review"' in candidate_routes
    assert '"admin_section": "market_identities"' in identity_routes
    assert '"admin_section": "readiness"' in data_status_routes
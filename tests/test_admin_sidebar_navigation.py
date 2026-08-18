from pathlib import Path


TEMPLATES = Path(__file__).resolve().parents[1] / "app" / "templates"


def test_admin_sidebar_contains_all_current_admin_features():
    sidebar = (TEMPLATES / "admin_sidebar.html").read_text(encoding="utf-8")
    expected_links = [
        "/admin?tab=dashboard",
        "/datenstatus",
        "/admin?tab=products",
        "/admin?tab=quality",
        "/admin?tab=categories",
        "/admin?tab=media",
        "/admin?tab=stores",
        "/admin/coverage",
        "/admin/collector",
        "/admin/articles/prospect-audit",
        "/admin/quality/provenance",
        "/admin?tab=settings",
        "/admin?tab=audit",
        "/admin/support-export.zip",
    ]
    for link in expected_links:
        assert link in sidebar


def test_all_admin_workspaces_use_shared_sidebar():
    expected_sections = {
        "admin.html": "admin_sidebar.html",
        "admin_collector.html": "admin_section = 'collector'",
        "admin_coverage.html": "admin_section = 'coverage'",
        "admin_prospect_audit.html": "admin_section = 'prospect_audit'",
        "admin_provenance.html": "admin_section = 'provenance'",
    }
    for filename, marker in expected_sections.items():
        content = (TEMPLATES / filename).read_text(encoding="utf-8")
        assert "admin_sidebar.html" in content
        assert marker in content

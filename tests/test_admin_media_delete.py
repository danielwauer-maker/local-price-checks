from pathlib import Path


def test_admin_media_delete_route_and_button_are_present():
    route_source = Path("app/admin_media_routes.py").read_text(encoding="utf-8")
    sidebar_source = Path("app/templates/admin_sidebar.html").read_text(encoding="utf-8")
    api_main_source = Path("app/api_main.py").read_text(encoding="utf-8")

    assert '@router.post("/admin/media/{media_id}/delete")' in route_source
    assert "local_file.unlink()" in route_source
    assert "media_deleted" in route_source
    assert "/admin/media/" in sidebar_source and "/delete" in sidebar_source
    assert "wirklich dauerhaft löschen" in sidebar_source
    assert "admin_media_router" in api_main_source

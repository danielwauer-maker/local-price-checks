from app.api_main import app


def test_market_identity_admin_routes_are_registered_once():
    routes = [(route.path, method) for route in app.routes for method in getattr(route, "methods", set())]

    assert routes.count(("/admin/market-identities", "GET")) == 1
    assert routes.count(("/admin/market-identities/{store_id}/delete", "POST")) == 1


def test_candidate_promotion_has_one_central_route():
    routes = [(route.path, method) for route in app.routes for method in getattr(route, "methods", set())]

    assert routes.count(("/admin/coverage/candidates/{candidate_id}/promote", "POST")) == 1

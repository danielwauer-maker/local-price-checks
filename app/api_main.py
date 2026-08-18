import re
import secrets

from .main import app
from .api_routes import router
from .client_routes import router as client_router
from .admin_routes import router as admin_router
from .admin_users_routes import router as admin_users_router
from .admin_data_status_routes import router as admin_data_status_router
from .admin_media_routes import router as admin_media_router
from .admin_collector_routes import router as admin_collector_router
from .admin_provenance_routes import router as admin_provenance_router
from .admin_prospect_audit_routes import router as admin_prospect_audit_router
from .admin_coverage_routes import router as admin_coverage_router
from .coverage_routes import router as coverage_router
from .coverage_models import CoverageRegion  # noqa: F401 - registers additive table before startup create_all
from .client_models import UserClient  # noqa: F401 - registers additive table before startup create_all
from .client_context import reset_client_key, set_client_key
from .config import settings
from .coverage_service import seed_initial_coverage
from .media_routes import router as media_router
from .ux_routes import router as ux_router
from .prospect_routes import router as prospect_router
from .admin_seed import seed_admin_catalog
from .category_classifier import backfill_auto_categories
from .db import SessionLocal

_CLIENT_RE = re.compile(r"^[A-Za-z0-9_-]{16,80}$")


@app.middleware("http")
async def persistent_client_identity(request, call_next):
    """Give browsers/PWAs a durable anonymous identity without changing first-request legacy behavior."""
    raw = request.cookies.get("lp_client_id") or request.headers.get("x-localprices-client") or ""
    has_client_identity = bool(_CLIENT_RE.fullmatch(raw))
    client_key = raw if has_client_identity else secrets.token_urlsafe(24)

    # Only an identity the browser already sent belongs to the current request.
    # A first visit still uses the legacy/default profile; the generated ID is
    # returned as a cookie and takes effect from the next request onward.
    token = set_client_key(client_key if has_client_identity else None)
    try:
        response = await call_next(request)
    finally:
        reset_client_key(token)

    response.set_cookie(
        "lp_client_id",
        client_key,
        max_age=60 * 60 * 24 * 365 * 2,
        path="/",
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
    )
    return response


app.include_router(router)
app.include_router(client_router)
app.include_router(admin_router)
app.include_router(admin_users_router)
app.include_router(admin_data_status_router)
app.include_router(admin_media_router)
app.include_router(admin_collector_router)
app.include_router(admin_provenance_router)
app.include_router(admin_prospect_audit_router)
app.include_router(admin_coverage_router)
app.include_router(coverage_router)
app.include_router(media_router)
app.include_router(ux_router)
app.include_router(prospect_router)


@app.on_event("startup")
def startup_admin_catalog():
    db = SessionLocal()
    try:
        seed_admin_catalog(db)
        backfill_auto_categories(db)
        seed_initial_coverage(db)
    finally:
        db.close()

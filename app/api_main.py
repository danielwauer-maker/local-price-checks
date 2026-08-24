import re
import secrets

from .main import app
from .api_routes import router
from .product_detail_routes import router as product_detail_router
from .client_routes import router as client_router
from .activity_routes import router as activity_router
from .admin_routes import router as admin_router
from .admin_users_routes import router as admin_users_router
from .admin_data_status_routes import router as admin_data_status_router
from .admin_media_routes import router as admin_media_router
from .admin_product_media_routes import router as admin_product_media_router
from .admin_collector_routes import router as admin_collector_router
from .admin_provenance_routes import router as admin_provenance_router
from .admin_prospect_audit_routes import router as admin_prospect_audit_router
from .admin_coverage_routes import router as admin_coverage_router
from .coverage_routes import router as coverage_router
from .lokero_routes import router as lokero_router
from .lokero_admin_routes import router as lokero_admin_router
from .coverage_models import CoverageRegion  # noqa: F401 - registers additive table before startup create_all
from .client_models import UserClient, ClientDevice  # noqa: F401 - registers additive tables before startup create_all
from .activity_models import ClientActivityDay, ClientFeatureUsage, ClientUsageSession  # noqa: F401 - registers additive analytics tables
from .lokero_models import NormalPriceObservation, ReviewerDeviceGrant, RegionInterest  # noqa: F401 - registers additive Lokero tables
from .client_context import (
    reset_client_key,
    reset_legacy_client_key,
    set_client_key,
    set_legacy_client_key,
)
from .config import settings
from .coverage_service import seed_initial_coverage
from .media_routes import router as media_router
from .ux_routes import router as ux_router
from .prospect_routes import router as prospect_router
from .offer_review_routes import router as offer_review_router
from .upcoming_routes import router as upcoming_router
from .admin_seed import seed_admin_catalog
from .category_classifier import backfill_auto_categories
from .normal_prices import backfill_explicit_references
from .db import SessionLocal

_CLIENT_RE = re.compile(r"^[A-Za-z0-9_-]{16,80}$")


@app.middleware("http")
async def persistent_client_identity(request, call_next):
    """Give each browser/PWA installation one durable anonymous identity.

    Current clients persist an opaque device key in localStorage and send it as
    ``X-LocalPrices-Client``. Prefer that value over the legacy cookie, but keep
    the valid cookie identity in request context for one-time migration. This
    lets an existing browser adopt the new device key without losing the
    UserProfile that already owns its location, favorites or shopping state.
    """
    header_key = request.headers.get("x-localprices-client") or ""
    cookie_key = request.cookies.get("lp_client_id") or ""
    valid_header = header_key if _CLIENT_RE.fullmatch(header_key) else ""
    valid_cookie = cookie_key if _CLIENT_RE.fullmatch(cookie_key) else ""
    client_key = valid_header or valid_cookie or secrets.token_urlsafe(24)
    legacy_key = valid_cookie if valid_header and valid_cookie and valid_cookie != valid_header else None

    token = set_client_key(client_key)
    legacy_token = set_legacy_client_key(legacy_key)
    try:
        response = await call_next(request)
    finally:
        reset_legacy_client_key(legacy_token)
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
app.include_router(product_detail_router)
app.include_router(client_router)
app.include_router(activity_router)
app.include_router(admin_router)
app.include_router(admin_users_router)
app.include_router(admin_data_status_router)
app.include_router(admin_media_router)
app.include_router(admin_product_media_router)
app.include_router(admin_collector_router)
app.include_router(admin_provenance_router)
app.include_router(admin_prospect_audit_router)
app.include_router(admin_coverage_router)
app.include_router(coverage_router)
app.include_router(lokero_router)
app.include_router(lokero_admin_router)
app.include_router(media_router)
app.include_router(ux_router)
app.include_router(prospect_router)
app.include_router(offer_review_router)
app.include_router(upcoming_router)


@app.on_event("startup")
def startup_admin_catalog():
    db = SessionLocal()
    try:
        seed_admin_catalog(db)
        backfill_auto_categories(db)
        seed_initial_coverage(db)
        backfill_explicit_references(db)
    finally:
        db.close()

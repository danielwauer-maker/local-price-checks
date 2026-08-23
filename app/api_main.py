import re
import secrets

from .main import app
from .api_routes import router
from .product_detail_routes import router as product_detail_router
from .client_routes import router as client_router
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
from .coverage_models import CoverageRegion  # noqa: F401 - registers additive table before startup create_all
from .client_models import UserClient, ClientDevice  # noqa: F401 - registers additive tables before startup create_all
from .client_context import reset_client_key, set_client_key
from .config import settings
from .coverage_service import seed_initial_coverage
from .media_routes import router as media_router
from .ux_routes import router as ux_router
from .prospect_routes import router as prospect_router
from .offer_review_routes import router as offer_review_router
from .admin_seed import seed_admin_catalog
from .category_classifier import backfill_auto_categories
from .db import SessionLocal

_CLIENT_RE = re.compile(r"^[A-Za-z0-9_-]{16,80}$")


@app.middleware("http")
async def persistent_client_identity(request, call_next):
    """Give each browser/PWA installation one durable anonymous identity.

    Current clients persist an opaque device key in localStorage and send it as
    ``X-LocalPrices-Client``. Prefer that value over the legacy cookie so an
    early bootstrap request cannot permanently pin the browser to a second,
    randomly generated anonymous profile. The cookie remains a two-year
    fallback for older clients and non-JavaScript requests.
    """
    header_key = request.headers.get("x-localprices-client") or ""
    cookie_key = request.cookies.get("lp_client_id") or ""
    raw = header_key if _CLIENT_RE.fullmatch(header_key) else cookie_key
    client_key = raw if _CLIENT_RE.fullmatch(raw) else secrets.token_urlsafe(24)
    token = set_client_key(client_key)
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
app.include_router(product_detail_router)
app.include_router(client_router)
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
app.include_router(media_router)
app.include_router(ux_router)
app.include_router(prospect_router)
app.include_router(offer_review_router)


@app.on_event("startup")
def startup_admin_catalog():
    db = SessionLocal()
    try:
        seed_admin_catalog(db)
        backfill_auto_categories(db)
        seed_initial_coverage(db)
    finally:
        db.close()

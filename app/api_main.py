import logging
import re
import secrets
from time import perf_counter

from .main import app
from . import account_change_events as account_change_events  # noqa: F401 - publishes canonical account changes
from . import sharing_change_events as sharing_change_events  # noqa: F401 - publishes shared-list revisions
from . import push_change_events as push_change_events  # noqa: F401 - aggregates shared-list push notifications
from . import offer_push_events as offer_push_events  # noqa: F401 - publishes favorite-offer push digests
from .api_routes import router
from .bootstrap_routes import router as bootstrap_router
from .product_detail_routes import router as product_detail_router
from .client_routes import router as client_router
from .activity_routes import router as activity_router
from .account_routes import router as account_router
from .profile_routes import router as profile_router
from .push_routes import router as push_router
from .realtime_routes import router as realtime_router
from .admin_routes import router as admin_router
from .admin_users_routes import router as admin_users_router
from .admin_data_status_routes import router as admin_data_status_router
from .admin_media_routes import router as admin_media_router
from .admin_product_media_routes import router as admin_product_media_router
from .admin_collector_routes import router as admin_collector_router
from .admin_provenance_routes import router as admin_provenance_router
from .admin_prospect_audit_routes import router as admin_prospect_audit_router
from .admin_web_offer_audit_routes import router as admin_web_offer_audit_router
from .admin_candidate_coordinate_routes import router as admin_candidate_coordinate_router
from .admin_coverage_canonical_routes import router as admin_coverage_canonical_router
from .admin_coverage_routes import router as admin_coverage_router
from .admin_rollout_routes import router as admin_rollout_router
from .coverage_routes import router as coverage_router
from .lokero_routes import router as lokero_router
from .lokero_state_routes import router as lokero_state_router
from .lokero_admin_routes import router as lokero_admin_router
from .lokero_media_routes import router as lokero_media_router
from .sharing_routes import router as sharing_router
from . import model_registry as model_registry  # noqa: F401 - registers the complete schema
from .coverage_models import CoverageRegion  # noqa: F401 - imported for existing route references
from .client_models import (  # noqa: F401 - registers additive tables before startup create_all
    AccountClientLink,
    AccountIdentity,
    ClientDevice,
    UserClient,
)
from .activity_models import ClientActivityDay, ClientFeatureUsage, ClientUsageSession  # noqa: F401 - registers additive analytics tables
from .lokero_models import (  # noqa: F401 - registers additive Lokero tables
    FavoriteProductFamily,
    FavoriteProductPreference,
    NormalPriceObservation,
    RegionInterest,
    ReviewerDeviceGrant,
)
from .push_models import PushSubscription  # noqa: F401 - registers additive push table
from .client_context import (
    reset_client_key,
    reset_legacy_client_key,
    reset_request_method,
    set_client_key,
    set_legacy_client_key,
    set_request_method,
)
from .config import settings
from .coverage_service import seed_initial_coverage
from .postcode_coverage_service import seed_initial_postcode_coverage
from .media_routes import router as media_router
from .ux_routes import router as ux_router
from .prospect_routes import router as prospect_router
from .offer_review_routes import router as offer_review_router
from .upcoming_routes import router as upcoming_router
from .admin_seed import seed_admin_catalog
from .normal_prices import backfill_explicit_references
from .db import SessionLocal, begin_request_query_metrics, end_request_query_metrics

_CLIENT_RE = re.compile(r"^[A-Za-z0-9_-]{16,80}$")
_PERFORMANCE_PATHS = (
    "/api/bootstrap",
    "/api/account/",
    "/api/sharing/lists",
    "/api/push/",
)
_performance_logger = logging.getLogger("spareno.performance")


@app.middleware("http")
async def persistent_client_identity(request, call_next):
    """Give each browser/PWA installation one durable opaque client key.

    The key itself is cheap and may be issued on a read-only request. A database
    UserProfile/UserClient is materialized lazily only when a real personal
    write occurs (or when an existing client/account already resolves).
    """
    header_key = request.headers.get("x-localprices-client") or ""
    cookie_key = request.cookies.get("lp_client_id") or ""
    valid_header = header_key if _CLIENT_RE.fullmatch(header_key) else ""
    valid_cookie = cookie_key if _CLIENT_RE.fullmatch(cookie_key) else ""
    client_key = valid_header or valid_cookie or secrets.token_urlsafe(24)
    legacy_key = valid_cookie if valid_header and valid_cookie and valid_cookie != valid_header else None

    token = set_client_key(client_key)
    legacy_token = set_legacy_client_key(legacy_key)
    method_token = set_request_method(request.method)
    try:
        response = await call_next(request)
    finally:
        reset_request_method(method_token)
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


@app.middleware("http")
async def request_performance_metrics(request, call_next):
    if not request.url.path.startswith(_PERFORMANCE_PATHS):
        return await call_next(request)
    metrics, token = begin_request_query_metrics()
    started = perf_counter()
    response = None
    try:
        response = await call_next(request)
        return response
    finally:
        duration_ms = (perf_counter() - started) * 1000
        _performance_logger.info(
            "api_request method=%s path=%s status=%s duration_ms=%.2f query_count=%s",
            request.method,
            request.url.path,
            getattr(response, "status_code", 500),
            duration_ms,
            metrics["queries"],
        )
        end_request_query_metrics(token)


# Optimized bootstrap is intentionally registered before the legacy /api/bootstrap route.
app.include_router(bootstrap_router)
app.include_router(router)
app.include_router(product_detail_router)
app.include_router(client_router)
app.include_router(activity_router)
app.include_router(account_router)
app.include_router(profile_router)
app.include_router(push_router)
# Register the event-driven list stream before the legacy polling route with the same path.
app.include_router(realtime_router)
app.include_router(admin_router)
app.include_router(admin_users_router)
app.include_router(admin_data_status_router)
app.include_router(admin_media_router)
app.include_router(admin_product_media_router)
app.include_router(admin_collector_router)
app.include_router(admin_provenance_router)
app.include_router(admin_prospect_audit_router)
app.include_router(admin_web_offer_audit_router)
app.include_router(admin_rollout_router)
# Canonical coverage GET must be registered before the legacy raw Store GET.
app.include_router(admin_coverage_canonical_router)
# Keep the existing Coverage coordinate-review/write routes unchanged.
app.include_router(admin_candidate_coordinate_router)
app.include_router(admin_coverage_router)
app.include_router(coverage_router)
app.include_router(lokero_router)
app.include_router(lokero_state_router)
app.include_router(lokero_admin_router)
app.include_router(lokero_media_router)
app.include_router(sharing_router)
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
        seed_initial_coverage(db)
        seed_initial_postcode_coverage(db)
        backfill_explicit_references(db)
    finally:
        db.close()

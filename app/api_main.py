from .main import app
from .api_routes import router
from .admin_routes import router as admin_router
from .admin_collector_routes import router as admin_collector_router
from .admin_provenance_routes import router as admin_provenance_router
from .admin_prospect_audit_routes import router as admin_prospect_audit_router
from .admin_coverage_routes import router as admin_coverage_router
from .coverage_routes import router as coverage_router
from .coverage_models import CoverageRegion  # noqa: F401 - registers additive table before startup create_all
from .media_routes import router as media_router
from .ux_routes import router as ux_router
from .prospect_routes import router as prospect_router
from .admin_seed import seed_admin_catalog
from .category_classifier import backfill_auto_categories
from .db import SessionLocal

app.include_router(router)
app.include_router(admin_router)
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
    finally:
        db.close()

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .admin_coverage_routes import safe_external_url
from .admin_routes import _admin
from .coverage_models import CoveragePostalCode, CoverageRegion, StoreDiscoveryCandidate
from .coverage_service import coverage_payload, stores_in_region
from .db import get_db
from .market_activation import activation_overview
from .models import Store
from .physical_market_identity import collapse_physical_stores
from .postcode_coverage_service import candidate_ready_for_promotion
from .postcode_geometry import OSM_ATTRIBUTION, OSM_LICENSE_URL, postcode_feature
from .postcode_reconciliation import deduplicate_candidates, reconcile_postcode_coverage

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE / "templates")
router = APIRouter()


@router.get("/admin/coverage")
def canonical_coverage_admin(
    request: Request,
    result: str = "",
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    """Render Coverage/Activation with one row per physical grocery market.

    Write endpoints stay in ``admin_coverage_routes``. Keeping this as a narrow
    read adapter means existing workflow actions are unchanged while duplicate
    Store provenance rows can no longer appear as separate physical markets.
    """
    regions = db.query(CoverageRegion).order_by(CoverageRegion.created_at.desc()).all()
    payloads = {region.id: coverage_payload(db, region) for region in regions}
    stores = {region.id: stores_in_region(db, region) for region in regions}
    postcodes = db.query(CoveragePostalCode).order_by(CoveragePostalCode.postal_code).all()

    candidates = db.query(StoreDiscoveryCandidate).order_by(
        StoreDiscoveryCandidate.postal_code,
        StoreDiscoveryCandidate.retailer,
        StoreDiscoveryCandidate.name,
    ).all()
    raw_candidates_by_postcode: dict[str, list[StoreDiscoveryCandidate]] = defaultdict(list)
    for candidate in candidates:
        raw_candidates_by_postcode[candidate.postal_code].append(candidate)
    candidates_by_postcode = {
        postal_code: deduplicate_candidates(rows)
        for postal_code, rows in raw_candidates_by_postcode.items()
    }

    postcode_values = [postcode.postal_code for postcode in postcodes]
    raw_postcode_stores = (
        db.query(Store)
        .filter(Store.postal_code.in_(postcode_values))
        .order_by(Store.postal_code, Store.retailer, Store.name)
        .all()
        if postcode_values
        else []
    )
    postcode_stores = collapse_physical_stores(raw_postcode_stores)
    stores_by_postcode: dict[str, list[Store]] = defaultdict(list)
    for store in postcode_stores:
        stores_by_postcode[store.postal_code].append(store)

    activation_overviews = {
        store.id: activation_overview(db, store)
        for store in postcode_stores
    }
    safe_candidate_source_urls = {
        candidate.id: safe_external_url(candidate.source_url)
        for candidate in candidates
    }
    summaries = {
        postcode.postal_code: reconcile_postcode_coverage(db, postcode)
        for postcode in postcodes
    }
    features = []
    for postcode in postcodes:
        summary = summaries[postcode.postal_code]
        feature = postcode_feature(postcode, summary.as_dict())
        if feature:
            features.append(feature)

    return templates.TemplateResponse(
        "admin_coverage.html",
        {
            "request": request,
            "actor": actor,
            "admin_section": "coverage",
            "regions": regions,
            "payloads": payloads,
            "stores": stores,
            "postcodes": postcodes,
            "candidates_by_postcode": candidates_by_postcode,
            "stores_by_postcode": dict(stores_by_postcode),
            "activation_overviews": activation_overviews,
            "safe_candidate_source_urls": safe_candidate_source_urls,
            "coverage_summaries": summaries,
            "postcode_geojson": {"type": "FeatureCollection", "features": features},
            "osm_attribution": OSM_ATTRIBUTION,
            "osm_license_url": OSM_LICENSE_URL,
            "candidate_ready_for_promotion": candidate_ready_for_promotion,
            "result": result,
        },
    )

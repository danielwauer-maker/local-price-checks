from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .coverage_models import CoverageRegion
from .coverage_service import coverage_payload
from .db import get_db

router = APIRouter(prefix="/api/coverage")


@router.get("")
def coverage_regions(db: Session = Depends(get_db)):
    regions = (
        db.query(CoverageRegion)
        .filter(CoverageRegion.active.is_(True))
        .order_by(CoverageRegion.status.desc(), CoverageRegion.name)
        .all()
    )
    return [coverage_payload(db, region) for region in regions]

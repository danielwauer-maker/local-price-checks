#!/usr/bin/env python3
"""Repair reviewed legacy public Store.active projections for beta REWE stores.

The durable publication state lives in ``store_activation_states``. Historical
rows can therefore be ``lifecycle_status=public`` with a publication timestamp
while the legacy ``stores.active`` projection is still false. This script fixes
only the three production-audited stores listed below, and only when every
reviewed invariant still matches. Run without ``--apply`` for a read-only dry
run.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import SessionLocal


@dataclass(frozen=True)
class ProjectionRepairSpec:
    store_id: int
    retailer: str
    postal_code: str
    address: str
    external_id: str


REPAIRS = (
    ProjectionRepairSpec(9, "REWE", "57610", "Bahnhofstr. 30", "8534500"),
    ProjectionRepairSpec(10, "REWE", "57610", "Dammweg 10", "2500021"),
    ProjectionRepairSpec(13, "REWE", "65618", "Am Schwimmbad 1", "240052"),
)


def _abort(message: str) -> None:
    raise RuntimeError(message)


def _store(db: Session, store_id: int):
    return db.execute(
        text(
            """SELECT id, retailer, name, postal_code, city, address, active,
                      benchmark_verified, external_id, source_url
               FROM stores WHERE id = :store_id"""
        ),
        {"store_id": store_id},
    ).mappings().first()


def _activation(db: Session, store_id: int):
    return db.execute(
        text(
            """SELECT store_id, lifecycle_status, identity_verified,
                      last_test_run_id, published_at, manually_suspended,
                      suspension_reason, suspended_at
               FROM store_activation_states WHERE store_id = :store_id"""
        ),
        {"store_id": store_id},
    ).mappings().first()


def _validate(db: Session, spec: ProjectionRepairSpec):
    store = _store(db, spec.store_id)
    if store is None:
        _abort(f"Store {spec.store_id} is missing")
    if store["retailer"] != spec.retailer:
        _abort(f"Store {spec.store_id} has unexpected retailer {store['retailer']!r}")
    if store["postal_code"] != spec.postal_code:
        _abort(f"Store {spec.store_id} has unexpected postcode {store['postal_code']!r}")
    if store["address"] != spec.address:
        _abort(f"Store {spec.store_id} has unexpected address {store['address']!r}")
    if store["external_id"] != spec.external_id:
        _abort(f"Store {spec.store_id} has unexpected external_id {store['external_id']!r}")
    if not bool(store["benchmark_verified"]):
        _abort(f"Store {spec.store_id} is not benchmark verified")

    activation = _activation(db, spec.store_id)
    if activation is None:
        _abort(f"Store {spec.store_id} activation state is missing")
    if not (
        activation["lifecycle_status"] == "public"
        and bool(activation["identity_verified"])
        and activation["last_test_run_id"] is not None
        and activation["published_at"] is not None
        and not bool(activation["manually_suspended"])
        and activation["suspended_at"] is None
    ):
        _abort(
            f"Store {spec.store_id} activation state is not reviewed-public: "
            f"{dict(activation)!r}"
        )
    return store, activation


def repair_legacy_public_projections(db: Session, *, apply: bool = False) -> list[dict]:
    reports: list[dict] = []
    try:
        for spec in REPAIRS:
            store, activation = _validate(db, spec)
            already_correct = bool(store["active"])
            reports.append(
                {
                    "store_id": spec.store_id,
                    "before": dict(store),
                    "activation": dict(activation),
                    "legacy_inactive_public_projection": not already_correct,
                    "already_correct": already_correct,
                }
            )
            if apply and not already_correct:
                db.execute(
                    text("UPDATE stores SET active = 1 WHERE id = :store_id"),
                    {"store_id": spec.store_id},
                )
                db.flush()
                repaired, activation_after = _validate(db, spec)
                if not bool(repaired["active"]):
                    _abort(f"Store {spec.store_id} active projection was not restored")
                if dict(activation_after) != dict(activation):
                    _abort(f"Store {spec.store_id} activation state changed unexpectedly")

        if apply:
            fk_errors = db.execute(text("PRAGMA foreign_key_check")).all()
            if fk_errors:
                _abort(f"foreign_key_check failed: {fk_errors!r}")
            db.commit()
            db.expire_all()
        else:
            db.rollback()
            db.expire_all()
        return reports
    except Exception:
        db.rollback()
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        reports = repair_legacy_public_projections(db, apply=args.apply)
        for report in reports:
            print(report)
        print("action=applied" if args.apply else "action=dry-run; no changes written")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

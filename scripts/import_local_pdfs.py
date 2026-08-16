from __future__ import annotations

import argparse
from pathlib import Path

from app.collection_service import collect_pdf_for_store
from app.db import Base, SessionLocal, engine
from app.seed import seed_stores


def _import(db, store: str, path: Path):
    parsed, summary, run = collect_pdf_for_store(db, store, path)
    print(
        f"{store}: status={run.status} parsed={len(parsed.rows)} "
        f"imported={summary.imported} skipped={summary.skipped}"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Import local REWE/Netto/ALDI prospect PDFs into the mobile MVP database."
    )
    parser.add_argument("--rewe", type=Path, required=True, help="REWE Dierdorf prospect PDF")
    parser.add_argument("--netto", type=Path, required=True, help="Netto regional prospect PDF")
    parser.add_argument("--aldi", type=Path, required=True, help="ALDI SÜD regional prospect PDF")
    args = parser.parse_args()

    for path in (args.rewe, args.netto, args.aldi):
        if not path.exists():
            raise SystemExit(f"PDF nicht gefunden: {path}")

    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        seed_stores(db)
        _import(db, "REWE:XL Hundertmark", args.rewe)
        # Netto and ALDI prospects are regional in the current MVP test area, so
        # the same validated prospect is imported into both explicitly selected
        # local stores. Store identity remains separate in the database.
        _import(db, "Netto Dierdorf", args.netto)
        _import(db, "Netto Oberhonnefeld-Gierend", args.netto)
        _import(db, "ALDI SÜD Dierdorf", args.aldi)
        _import(db, "ALDI SÜD Oberhonnefeld-Gierend", args.aldi)
    finally:
        db.close()


if __name__ == "__main__":
    main()

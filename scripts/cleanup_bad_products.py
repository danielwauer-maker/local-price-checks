from __future__ import annotations

import argparse

from app.db import SessionLocal
from app.engine_v140.product_cleaning import product_name_issue
from app.models import FavoriteProduct, MasterProduct, Offer, ProductBarcode, ShoppingItem
from app.offer_cleanup import delete_offer_graph


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove imported master products that are clearly descriptor/navigation fragments.")
    parser.add_argument("--apply", action="store_true", help="Actually delete rows. Without this flag only report candidates.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        candidates = []
        for product in db.query(MasterProduct).order_by(MasterProduct.id).all():
            issue = product_name_issue(product.name)
            if issue:
                candidates.append((product, issue))

        print(f"Bad product candidates: {len(candidates)}")
        for product, issue in candidates[:100]:
            print(f"- id={product.id} name={product.name!r} reason={issue}")
        if len(candidates) > 100:
            print(f"... and {len(candidates) - 100} more")

        if not args.apply:
            print("Dry run only. Re-run with --apply to delete these products and dependent offer/user-link rows.")
            return

        ids = [product.id for product, _ in candidates]
        if not ids:
            print("Nothing to delete.")
            return

        offer_ids = [row[0] for row in db.query(Offer.id).filter(Offer.master_product_id.in_(ids)).all()]
        offer_result = delete_offer_graph(db, offer_ids)
        deleted_favorites = db.query(FavoriteProduct).filter(FavoriteProduct.master_product_id.in_(ids)).delete(synchronize_session=False)
        deleted_shopping = db.query(ShoppingItem).filter(ShoppingItem.master_product_id.in_(ids)).delete(synchronize_session=False)
        deleted_barcodes = db.query(ProductBarcode).filter(ProductBarcode.master_product_id.in_(ids)).delete(synchronize_session=False)
        deleted_products = db.query(MasterProduct).filter(MasterProduct.id.in_(ids)).delete(synchronize_session=False)
        db.commit()

        print(
            "Deleted: "
            f"products={deleted_products}, offers={offer_result['offers']}, favorites={deleted_favorites}, "
            f"shopping={deleted_shopping}, barcodes={deleted_barcodes}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()

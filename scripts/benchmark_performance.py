"""Run a small, deterministic local API performance series.

The script never creates production data. Point ``DATABASE_URL`` at a disposable
SQLite copy (or a dedicated PostgreSQL test database) before invoking it.
"""

from __future__ import annotations

import json
import os
import statistics
from collections.abc import Callable
from datetime import timedelta
from time import perf_counter

from fastapi.testclient import TestClient
from sqlalchemy import event, text

if "DATABASE_URL" not in os.environ:
    raise SystemExit("Set DATABASE_URL to a disposable benchmark database")

os.environ.setdefault("AUTO_CREATE_SCHEMA", "false")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ROUTING_BASE_URL", "http://127.0.0.1:9")
os.environ.setdefault("ROUTING_TIMEOUT_SECONDS", "0.05")

from app.api_main import app  # noqa: E402
from app.clock import app_today  # noqa: E402
from app.client_models import UserClient  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import (  # noqa: E402
    FavoriteStore,
    MasterProduct,
    Offer,
    ProductAdminData,
    ProductCategory,
    Store,
    UserProfile,
)


BENCHMARK_CLIENT_KEY = "spareno-performance-benchmark-client"


def seed_benchmark_dataset() -> None:
    """Populate an empty disposable database with a stable, non-production fixture."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(UserClient.id).filter(UserClient.client_key == BENCHMARK_CLIENT_KEY).first() is not None:
            return
        populated_tables = {
            "users": db.query(UserProfile.id).first(),
            "stores": db.query(Store.id).first(),
            "products": db.query(MasterProduct.id).first(),
            "offers": db.query(Offer.id).first(),
        }
        if any(populated_tables.values()):
            raise SystemExit(
                "Refusing to seed a non-empty database; use a fresh disposable DATABASE_URL"
            )
        today = app_today()
        user = UserProfile(
            display_name="Performance Benchmark",
            postal_code="56269",
            city="Dierdorf",
            latitude=50.6199,
            longitude=7.6264,
            radius_km=25,
        )
        category = ProductCategory(name="Benchmark Lebensmittel", slug="benchmark-lebensmittel", active=True)
        db.add_all([user, category])
        db.flush()
        stores = [
            Store(
                retailer=f"Benchmark {index % 5}",
                name=f"Benchmark Markt {index:02d}",
                postal_code="56269",
                city="Dierdorf",
                address=f"Testweg {index}",
                latitude=50.6199 + index * 0.001,
                longitude=7.6264 + index * 0.001,
                active=True,
                benchmark_verified=True,
                external_id=f"benchmark-{index}",
            )
            for index in range(10)
        ]
        db.add_all(stores)
        db.flush()
        db.add_all(FavoriteStore(user_id=user.id, store_id=store.id) for store in stores[:5])
        products = [
            MasterProduct(
                name=f"Benchmark Vollmilch Produkt {index:03d}",
                brand=f"Marke {index % 12}",
                package_size="1 l",
                normalized_key=f"benchmark-vollmilch-{index:03d}",
            )
            for index in range(300)
        ]
        db.add_all(products)
        db.flush()
        db.add_all(ProductAdminData(master_product_id=product.id, category_id=category.id) for product in products)
        for product_index, product in enumerate(products):
            for offset in range(4):
                store = stores[(product_index + offset) % len(stores)]
                db.add(Offer(
                    store_id=store.id,
                    master_product_id=product.id,
                    price=round(0.79 + (product_index % 30) * 0.03 + offset * 0.02, 2),
                    unit_price=round(0.79 + (product_index % 30) * 0.03 + offset * 0.02, 2),
                    unit_price_unit="l",
                    valid_from=today - timedelta(days=1),
                    valid_to=today + timedelta(days=6),
                    local_store_offer=True,
                ))
        db.add(UserClient(client_key=BENCHMARK_CLIENT_KEY, user_id=user.id))
        db.commit()
    finally:
        db.close()


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * fraction + 0.999999) - 1))
    return ordered[index]


def measure(client: TestClient, label: str, request: Callable[[], object], samples: int = 10) -> dict:
    durations: list[float] = []
    query_counts: list[int] = []
    response_sizes: list[int] = []

    response = request()
    if getattr(response, "status_code", 500) >= 400:
        raise RuntimeError(f"{label} warmup failed: {response.status_code} {response.text}")

    for _ in range(samples):
        queries = 0

        def count_query(*_args) -> None:
            nonlocal queries
            queries += 1

        event.listen(engine, "before_cursor_execute", count_query)
        started = perf_counter()
        try:
            response = request()
        finally:
            duration_ms = (perf_counter() - started) * 1000
            event.remove(engine, "before_cursor_execute", count_query)
        if response.status_code >= 400:
            raise RuntimeError(f"{label} failed: {response.status_code} {response.text}")
        durations.append(duration_ms)
        query_counts.append(queries)
        response_body = getattr(response, "content", None)
        if response_body is None:
            response_body = getattr(response, "body", b"")
        response_sizes.append(len(response_body))

    return {
        "label": label,
        "samples": samples,
        "latencyMs": {
            "p50": round(statistics.median(durations), 2),
            "p95": round(percentile(durations, 0.95), 2),
            "min": round(min(durations), 2),
            "max": round(max(durations), 2),
        },
        "queryCount": {
            "p50": int(statistics.median(query_counts)),
            "p95": int(percentile([float(value) for value in query_counts], 0.95)),
        },
        "responseBytes": int(statistics.median(response_sizes)),
    }


def main() -> None:
    seed_benchmark_dataset()
    today = app_today()
    db = SessionLocal()
    try:
        client_key = (
            db.query(UserClient.client_key)
            .filter(UserClient.client_key == BENCHMARK_CLIENT_KEY)
            .scalar()
        )
        product_ids = [
            str(row[0])
            for row in (
                db.query(Offer.master_product_id)
                .filter(Offer.valid_from <= today, Offer.valid_to >= today)
                .distinct()
                .limit(5)
                .all()
            )
        ]
        dataset = {
            "products": db.query(Offer.master_product_id).distinct().count(),
            "currentOffers": db.query(Offer).filter(Offer.valid_from <= today, Offer.valid_to >= today).count(),
            "alternativeSourceIds": product_ids,
        }
        if db.bind is not None and db.bind.dialect.name == "sqlite":
            dataset["queryPlans"] = {
                "currentOffers": [
                    row[3]
                    for row in db.execute(text(
                        "EXPLAIN QUERY PLAN SELECT id FROM offers "
                        "WHERE store_id IN (1, 2, 3, 4, 5) AND local_store_offer = 1 "
                        f"AND valid_from <= '{today.isoformat()}' AND valid_to >= '{today.isoformat()}' "
                        "ORDER BY price"
                    ))
                ],
                "latestOccurrences": [
                    row[3]
                    for row in db.execute(text(
                        "EXPLAIN QUERY PLAN SELECT id FROM offer_occurrences "
                        "WHERE offer_id IN (1, 2, 3, 4, 5) ORDER BY collected_at DESC, id DESC"
                    ))
                ],
            }
    finally:
        db.close()

    if not product_ids:
        raise SystemExit("Benchmark database has no current offers")

    headers = {"x-localprices-client": client_key} if client_key else {}
    with TestClient(app, headers=headers) as client:
        results = [
            measure(client, "bootstrap", lambda: client.get("/api/bootstrap")),
            measure(client, "markets", lambda: client.get("/api/lokero/markets")),
            measure(client, "offers", lambda: client.get("/api/lokero/offers?limit=250")),
        ]
        for count in (1, 3, 5):
            ids = product_ids[:count]

            def alternatives_series(ids: list[str] = ids):
                responses = [client.get(f"/api/lokero/list/products/{product_id}/alternatives") for product_id in ids]
                failed = next((response for response in responses if response.status_code >= 400), None)
                if failed is not None:
                    return failed
                payload = {product_id: response.json() for product_id, response in zip(ids, responses, strict=True)}
                from starlette.responses import Response

                return Response(json.dumps(payload), media_type="application/json")

            results.append(measure(client, f"alternatives-sequential-{count}", alternatives_series, samples=3))
        batch_ids = product_ids[:5]
        results.append(measure(
            client,
            "alternatives-batch-5",
            lambda: client.post(
                "/api/lokero/list/alternatives/batch",
                json={"productIds": batch_ids, "limit": 3},
            ),
        ))

    print(json.dumps({"dataset": dataset, "results": results}, indent=2))


if __name__ == "__main__":
    main()

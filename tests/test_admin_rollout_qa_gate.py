from pathlib import Path

# Importing the rollout module registers the compatibility guard for legacy
# Store.active toggles.
from app import admin_rollout_routes  # noqa: F401
from app.market_activation import store_is_public
from app.models import Store


def _store() -> Store:
    store = Store(
        retailer="ALDI SÜD",
        name="ALDI SÜD Dierdorf",
        postal_code="56269",
        city="Dierdorf",
        address="Teststraße 1",
        active=False,
        benchmark_verified=True,
    )
    # The guard intentionally applies only to persisted rows.
    store.id = 55
    return store


def test_legacy_active_toggle_cannot_republish_stale_benchmark_store():
    store = _store()
    store.benchmark_verified = True

    store.active = True

    assert store.active is True
    assert store.benchmark_verified is False
    assert store_is_public(store) is False


def test_explicit_publish_order_can_still_make_store_public():
    store = _store()
    store.benchmark_verified = False

    store.active = True
    store.benchmark_verified = True

    assert store_is_public(store) is True


def test_rollout_ui_separates_qa_activation_from_public_release():
    template = (Path(__file__).parents[1] / "app" / "templates" / "admin_rollout.html").read_text(
        encoding="utf-8"
    )
    assert "Für QA aktivieren" in template
    assert "QA aktiv · nicht öffentlich" in template
    assert "/admin/rollout/stores/{{ store.id }}/qa-enable" in template
    assert "Markt veröffentlichen" in template

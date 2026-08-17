from datetime import date, timedelta

from app import optimizer
from app.models import MasterProduct, Offer, ShoppingItem, Store, UserProfile


def _store(store_id: int, name: str) -> Store:
    store = Store(
        retailer="Test",
        name=name,
        postal_code="00000",
        city="Teststadt",
        address="Testweg 1",
        latitude=50.0,
        longitude=7.0,
    )
    store.id = store_id
    return store


def _item(item_id: int, product_id: int, name: str) -> ShoppingItem:
    product = MasterProduct(name=name, normalized_key=f"p-{product_id}")
    product.id = product_id
    item = ShoppingItem(user_id=1, master_product_id=product_id, quantity=1)
    item.id = item_id
    item.product = product
    return item


def _offer(store: Store, product_id: int, price: float) -> Offer:
    today = date.today()
    offer = Offer(
        store_id=store.id,
        master_product_id=product_id,
        price=price,
        valid_from=today,
        valid_to=today + timedelta(days=6),
        local_store_offer=True,
    )
    offer.store = store
    return offer


def test_optimizer_avoids_second_market_when_travel_cost_exceeds_price_saving(monkeypatch):
    user = UserProfile(display_name="Test", latitude=50.0, longitude=7.0, radius_km=20)
    user.id = 1
    a = _store(1, "Markt A")
    b = _store(2, "Markt B")
    item1 = _item(1, 101, "Produkt 1")
    item2 = _item(2, 102, "Produkt 2")

    offers = [
        _offer(a, 101, 2.00),
        _offer(a, 102, 2.00),
        _offer(b, 101, 1.80),
        _offer(b, 102, 2.50),
    ]
    monkeypatch.setattr(optimizer, "offers_for_selected_stores", lambda *_args, **_kwargs: offers)
    monkeypatch.setattr(
        optimizer,
        "_route_km",
        lambda _user, stores: 5.0 if {s.id for s in stores} == {1} else (12.0 if len(stores) > 1 else 10.0),
    )

    result = optimizer.optimize_shopping(None, user, [item1, item2], "current")

    assert [store.name for store in result.stores] == ["Markt A"]
    assert result.merchandise_total == 4.00
    assert result.total_with_travel == 4.75
    assert result.one_market_covers_all_offered_items is True


def test_optimizer_uses_second_market_when_total_cost_is_lower(monkeypatch):
    user = UserProfile(display_name="Test", latitude=50.0, longitude=7.0, radius_km=20)
    user.id = 1
    a = _store(1, "Markt A")
    b = _store(2, "Markt B")
    item1 = _item(1, 201, "Produkt 1")
    item2 = _item(2, 202, "Produkt 2")

    offers = [
        _offer(a, 201, 8.00),
        _offer(a, 202, 8.00),
        _offer(b, 201, 2.00),
        _offer(b, 202, 10.00),
    ]
    monkeypatch.setattr(optimizer, "offers_for_selected_stores", lambda *_args, **_kwargs: offers)
    monkeypatch.setattr(
        optimizer,
        "_route_km",
        lambda _user, stores: 5.0 if len(stores) == 1 else 8.0,
    )

    result = optimizer.optimize_shopping(None, user, [item1, item2], "current")

    assert {store.name for store in result.stores} == {"Markt A", "Markt B"}
    assert result.merchandise_total == 10.00
    assert result.total_with_travel == 11.20
    assert result.single_store_name == "Markt B"
    assert result.single_store_total == 12.75
    assert result.multi_store_worth_it is True
    assert result.multi_store_saving is not None and result.multi_store_saving > 0


def test_optimizer_returns_best_partial_plan_when_one_store_cannot_cover_everything(monkeypatch):
    user = UserProfile(display_name="Test", latitude=50.0, longitude=7.0, radius_km=20)
    user.id = 1
    a = _store(1, "Markt A")
    b = _store(2, "Markt B")
    item1 = _item(1, 301, "Produkt 1")
    item2 = _item(2, 302, "Produkt 2")
    item3 = _item(3, 303, "Produkt 3")

    offers = [
        _offer(a, 301, 2.00),
        _offer(a, 302, 3.00),
        _offer(b, 303, 1.00),
    ]
    monkeypatch.setattr(optimizer, "offers_for_selected_stores", lambda *_args, **_kwargs: offers)
    monkeypatch.setattr(optimizer, "_route_km", lambda _user, stores: 4.0 if stores else 0.0)

    result = optimizer.optimize_shopping(None, user, [item1, item2, item3], "current", max_stores=1)

    assert [store.name for store in result.stores] == ["Markt A"]
    assert result.covered_items == 2
    assert result.offered_items == 3
    assert result.merchandise_total == 5.00
    assert result.total_with_travel == 5.60
    assert sum(offer is None for _, offer in result.picks) == 1

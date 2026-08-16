from __future__ import annotations

from dataclasses import dataclass
from math import inf
from sqlalchemy.orm import Session

from .config import settings
from .geo import haversine_km
from .models import Offer, ShoppingItem, Store, UserProfile
from .services import offers_for_selected_stores


@dataclass
class PlanResult:
    picks: list[tuple[ShoppingItem, Offer | None]]
    merchandise_total: float
    travel_km: float
    travel_cost: float
    total_with_travel: float
    stores: list[Store]
    single_store_name: str | None
    single_store_total: float | None
    multi_store_saving: float | None
    multi_store_worth_it: bool | None


def _route_km(user: UserProfile, stores: list[Store]) -> float:
    if not stores or None in (user.latitude, user.longitude):
        return 0.0
    remaining = [s for s in stores if None not in (s.latitude, s.longitude)]
    if not remaining:
        return 0.0
    cur_lat, cur_lon = user.latitude, user.longitude
    km = 0.0
    while remaining:
        nxt = min(remaining, key=lambda s: haversine_km(cur_lat, cur_lon, s.latitude, s.longitude))
        km += haversine_km(cur_lat, cur_lon, nxt.latitude, nxt.longitude)
        cur_lat, cur_lon = nxt.latitude, nxt.longitude
        remaining.remove(nxt)
    km += haversine_km(cur_lat, cur_lon, user.latitude, user.longitude)
    return km * settings.route_distance_factor


def optimize_current_shopping(db: Session, user: UserProfile, items: list[ShoppingItem]) -> PlanResult:
    offers = offers_for_selected_stores(db, user, "current")
    by_product: dict[int, list[Offer]] = {}
    for offer in offers:
        by_product.setdefault(offer.master_product_id, []).append(offer)

    picks: list[tuple[ShoppingItem, Offer | None]] = []
    merchandise_total = 0.0
    selected_stores: dict[int, Store] = {}
    for item in items:
        opts = by_product.get(item.master_product_id, [])
        if not opts:
            picks.append((item, None))
            continue
        best = min(opts, key=lambda x: x.price)
        picks.append((item, best))
        merchandise_total += best.price * item.quantity
        selected_stores[best.store_id] = best.store

    stores = list(selected_stores.values())
    travel_km = _route_km(user, stores)
    travel_cost = travel_km * settings.driving_cost_per_km
    total_with_travel = merchandise_total + travel_cost

    # Best one-store alternative among selected stores. Only compare stores that
    # have an offer for every item that has at least one offer in the selected set.
    offered_items = [item for item in items if by_product.get(item.master_product_id)]
    candidate_store_ids = {o.store_id for o in offers}
    best_single_name = None
    best_single_total = inf
    for store_id in candidate_store_ids:
        line_total = 0.0
        complete = True
        store_obj = None
        for item in offered_items:
            opts = [o for o in by_product[item.master_product_id] if o.store_id == store_id]
            if not opts:
                complete = False
                break
            offer = min(opts, key=lambda x: x.price)
            store_obj = offer.store
            line_total += offer.price * item.quantity
        if not complete or store_obj is None:
            continue
        one_route_km = _route_km(user, [store_obj])
        total = line_total + one_route_km * settings.driving_cost_per_km
        if total < best_single_total:
            best_single_total = total
            best_single_name = store_obj.name

    if best_single_name is None:
        single_total = None
        saving = None
        worth = None
    else:
        single_total = best_single_total
        saving = single_total - total_with_travel
        worth = saving > 0.01 and len(stores) > 1

    return PlanResult(
        picks=picks,
        merchandise_total=merchandise_total,
        travel_km=travel_km,
        travel_cost=travel_cost,
        total_with_travel=total_with_travel,
        stores=stores,
        single_store_name=best_single_name,
        single_store_total=single_total,
        multi_store_saving=saving,
        multi_store_worth_it=worth,
    )

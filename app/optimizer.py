from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import inf

from sqlalchemy.orm import Session

from .config import settings
from .models import Offer, ShoppingItem, Store, UserProfile
from .routing import RoutingStop, optimized_roundtrip
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
    period: str
    total_items: int
    offered_items: int
    covered_items: int
    one_market_covers_all_offered_items: bool


def _route_km(user: UserProfile, stores: list[Store]) -> float:
    """Return the shortest available driving roundtrip for the selected stores.

    The routing adapter uses an OSRM road-distance matrix and evaluates every
    store order (at most three stores in the optimizer). Provider/network
    failures transparently fall back to the previous Haversine approximation.
    """
    if not stores or None in (user.latitude, user.longitude):
        return 0.0

    stops = [
        RoutingStop(
            key=str(store.id),
            latitude=float(store.latitude),
            longitude=float(store.longitude),
        )
        for store in stores
        if store.latitude is not None and store.longitude is not None
    ]
    if not stops:
        return 0.0

    result = optimized_roundtrip(
        float(user.latitude),
        float(user.longitude),
        stops,
        base_url=settings.routing_base_url,
        timeout_seconds=settings.routing_timeout_seconds,
        fallback_distance_factor=settings.route_distance_factor,
    )
    return result.distance_km


def _evaluate_store_set(
    user: UserProfile,
    offered_items: list[ShoppingItem],
    by_product: dict[int, list[Offer]],
    store_ids: set[int],
    *,
    require_full_coverage: bool = True,
) -> tuple[float, float, float, list[tuple[ShoppingItem, Offer]]]:
    picks: list[tuple[ShoppingItem, Offer]] = []
    merchandise_total = 0.0
    used_stores: dict[int, Store] = {}

    for item in offered_items:
        options = [o for o in by_product[item.master_product_id] if o.store_id in store_ids]
        if not options:
            if require_full_coverage:
                return 0.0, 0.0, inf, []
            continue
        best = min(options, key=lambda o: o.price)
        picks.append((item, best))
        merchandise_total += best.price * item.quantity
        used_stores[best.store_id] = best.store

    if not picks:
        return 0.0, 0.0, inf, []

    route_km = _route_km(user, list(used_stores.values()))
    total = merchandise_total + route_km * settings.driving_cost_per_km
    return merchandise_total, route_km, total, picks


def optimize_shopping(
    db: Session,
    user: UserProfile,
    items: list[ShoppingItem],
    period: str = "current",
    max_stores: int | None = None,
) -> PlanResult:
    period = "next" if period == "next" else "current"
    if max_stores is not None:
        max_stores = max(1, min(int(max_stores), 3))

    offers = offers_for_selected_stores(db, user, period)
    by_product: dict[int, list[Offer]] = {}
    stores_by_id: dict[int, Store] = {}
    for offer in offers:
        by_product.setdefault(offer.master_product_id, []).append(offer)
        stores_by_id[offer.store_id] = offer.store

    offered_list_items = [item for item in items if by_product.get(item.master_product_id)]
    candidate_store_ids = sorted(stores_by_id)

    best_total = inf
    best_merchandise = 0.0
    best_route_km = 0.0
    best_offer_picks: list[tuple[ShoppingItem, Offer]] = []
    best_store_ids: set[int] = set()

    if offered_list_items:
        combination_limit = len(candidate_store_ids)
        if max_stores is not None:
            combination_limit = min(combination_limit, max_stores)

        # First prefer a plan that covers every currently offered shopping item.
        for count in range(1, combination_limit + 1):
            for combo in combinations(candidate_store_ids, count):
                merchandise, route_km, total, offer_picks = _evaluate_store_set(
                    user,
                    offered_list_items,
                    by_product,
                    set(combo),
                    require_full_coverage=True,
                )
                if not offer_picks:
                    continue
                used_ids = {offer.store_id for _, offer in offer_picks}
                current_used = {offer.store_id for _, offer in best_offer_picks}
                better = total < best_total - 0.005
                tied_but_simpler = (
                    abs(total - best_total) <= 0.005
                    and (not current_used or len(used_ids) < len(current_used))
                )
                tied_same_stores_cheaper_goods = (
                    abs(total - best_total) <= 0.005
                    and len(used_ids) == len(current_used)
                    and merchandise < best_merchandise
                )
                if better or tied_but_simpler or tied_same_stores_cheaper_goods:
                    best_total = total
                    best_merchandise = merchandise
                    best_route_km = route_km
                    best_offer_picks = offer_picks
                    best_store_ids = used_ids

        # If the requested store limit cannot cover every offered item (most
        # notably max_stores=1), still return a useful plan. Prefer the store
        # combination covering the most shopping items, then the lowest total
        # including travel, then fewer actually used stores.
        if not best_offer_picks and max_stores is not None:
            best_coverage = 0
            for count in range(1, combination_limit + 1):
                for combo in combinations(candidate_store_ids, count):
                    merchandise, route_km, total, offer_picks = _evaluate_store_set(
                        user,
                        offered_list_items,
                        by_product,
                        set(combo),
                        require_full_coverage=False,
                    )
                    coverage = len(offer_picks)
                    if not coverage:
                        continue
                    used_ids = {offer.store_id for _, offer in offer_picks}
                    current_used = {offer.store_id for _, offer in best_offer_picks}
                    better_coverage = coverage > best_coverage
                    same_coverage_cheaper = coverage == best_coverage and total < best_total - 0.005
                    same_coverage_same_total_simpler = (
                        coverage == best_coverage
                        and abs(total - best_total) <= 0.005
                        and (not current_used or len(used_ids) < len(current_used))
                    )
                    if better_coverage or same_coverage_cheaper or same_coverage_same_total_simpler:
                        best_coverage = coverage
                        best_total = total
                        best_merchandise = merchandise
                        best_route_km = route_km
                        best_offer_picks = offer_picks
                        best_store_ids = used_ids

    best_by_item_id = {item.id: offer for item, offer in best_offer_picks}
    picks: list[tuple[ShoppingItem, Offer | None]] = [
        (item, best_by_item_id.get(item.id)) for item in items
    ]

    selected_stores = [stores_by_id[store_id] for store_id in best_store_ids]
    selected_stores.sort(key=lambda s: s.name)
    travel_cost = best_route_km * settings.driving_cost_per_km
    total_with_travel = 0.0 if best_total is inf else best_total

    # A single-store comparison is only meaningful when one store can cover
    # every shopping item that has an offer in the selected comparison set.
    best_single_name = None
    best_single_total = inf
    for store_id in candidate_store_ids:
        _, _, total, offer_picks = _evaluate_store_set(
            user,
            offered_list_items,
            by_product,
            {store_id},
            require_full_coverage=True,
        )
        if not offer_picks:
            continue
        if total < best_single_total:
            best_single_total = total
            best_single_name = stores_by_id[store_id].name

    if best_single_name is None:
        single_total = None
        saving = None
        worth = None
    else:
        single_total = best_single_total
        saving = single_total - total_with_travel
        worth = saving > 0.01 and len(selected_stores) > 1

    one_market_covers_all_offered_items = (
        bool(offered_list_items)
        and len(best_offer_picks) == len(offered_list_items)
        and len(selected_stores) == 1
        and best_single_name == selected_stores[0].name
    )

    return PlanResult(
        picks=picks,
        merchandise_total=best_merchandise,
        travel_km=best_route_km,
        travel_cost=travel_cost,
        total_with_travel=total_with_travel,
        stores=selected_stores,
        single_store_name=best_single_name,
        single_store_total=single_total,
        multi_store_saving=saving,
        multi_store_worth_it=worth,
        period=period,
        total_items=len(items),
        offered_items=len(offered_list_items),
        covered_items=len(best_offer_picks),
        one_market_covers_all_offered_items=one_market_covers_all_offered_items,
    )


def optimize_current_shopping(db: Session, user: UserProfile, items: list[ShoppingItem]) -> PlanResult:
    return optimize_shopping(db, user, items, "current")

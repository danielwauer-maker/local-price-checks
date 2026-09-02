from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import permutations
from math import inf
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .geo import haversine_km


@dataclass(frozen=True)
class RoutingStop:
    key: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class RoutingResult:
    distance_km: float
    source: str
    estimated: bool
    order: tuple[str, ...]


def _best_roundtrip_from_matrix(matrix: list[list[float | None]], stops: list[RoutingStop]) -> RoutingResult:
    """Return the shortest closed tour from point 0 through all stops and back.

    The matrix contains point 0 as the user's origin and points 1..N as the
    stores. Spareno currently evaluates at most three stores, so exhaustive
    permutation is both deterministic and cheaper/safer than a heuristic.
    """
    count = len(stops)
    if count == 0:
        return RoutingResult(0.0, "none", False, ())

    expected = count + 1
    if len(matrix) != expected or any(len(row) != expected for row in matrix):
        raise ValueError("routing matrix has unexpected dimensions")

    best_m = inf
    best_order: tuple[int, ...] | None = None
    for order in permutations(range(1, expected)):
        legs = ((0, order[0]),) + tuple(zip(order, order[1:])) + ((order[-1], 0),)
        total = 0.0
        valid = True
        for source, target in legs:
            distance = matrix[source][target]
            if distance is None:
                valid = False
                break
            total += float(distance)
        if valid and total < best_m:
            best_m = total
            best_order = order

    if best_order is None or best_m is inf:
        raise ValueError("routing matrix does not contain a complete roundtrip")

    return RoutingResult(
        distance_km=best_m / 1000.0,
        source="osrm",
        estimated=False,
        order=tuple(stops[index - 1].key for index in best_order),
    )


def _fallback_roundtrip(
    origin_lat: float,
    origin_lon: float,
    stops: list[RoutingStop],
    *,
    distance_factor: float,
) -> RoutingResult:
    if not stops:
        return RoutingResult(0.0, "none", False, ())

    best_km = inf
    best_order: tuple[RoutingStop, ...] | None = None
    for order in permutations(stops):
        cur_lat = origin_lat
        cur_lon = origin_lon
        total = 0.0
        for stop in order:
            total += haversine_km(cur_lat, cur_lon, stop.latitude, stop.longitude)
            cur_lat = stop.latitude
            cur_lon = stop.longitude
        total += haversine_km(cur_lat, cur_lon, origin_lat, origin_lon)
        total *= distance_factor
        if total < best_km:
            best_km = total
            best_order = order

    return RoutingResult(
        distance_km=0.0 if best_km is inf else best_km,
        source="haversine_fallback",
        estimated=True,
        order=tuple(stop.key for stop in (best_order or ())),
    )


def optimized_roundtrip(
    origin_lat: float | None,
    origin_lon: float | None,
    stops: list[RoutingStop],
    *,
    base_url: str,
    timeout_seconds: float,
    fallback_distance_factor: float,
) -> RoutingResult:
    """Calculate a shortest driving roundtrip, falling back safely to air distance.

    OSRM's table endpoint is used only to obtain a road-distance matrix. Route
    ordering remains local and exhaustive, making the optimizer independent of
    provider-specific trip heuristics. Network/provider failures never break
    shopping optimization; they fall back to the prior Haversine approximation.
    """
    if origin_lat is None or origin_lon is None or not stops:
        return RoutingResult(0.0, "missing_coordinates" if stops else "none", bool(stops), ())

    valid_stops = [
        stop
        for stop in stops
        if stop.latitude is not None and stop.longitude is not None
    ]
    if not valid_stops:
        return RoutingResult(0.0, "missing_coordinates", True, ())

    # If any requested stop has no coordinates, retain non-crashing legacy
    # behavior but make this an estimated result internally.
    incomplete_coordinates = len(valid_stops) != len(stops)

    try:
        coordinate_pairs = [(float(origin_lon), float(origin_lat))] + [
            (float(stop.longitude), float(stop.latitude)) for stop in valid_stops
        ]
        coordinates = ";".join(f"{lon:.7f},{lat:.7f}" for lon, lat in coordinate_pairs)
        query = urlencode({"annotations": "distance"})
        url = f"{base_url.rstrip('/')}/table/v1/driving/{coordinates}?{query}"
        request = Request(url, headers={"User-Agent": "Spareno/1.0 routing"})
        with urlopen(request, timeout=max(float(timeout_seconds), 0.1)) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("code") != "Ok" or not isinstance(payload.get("distances"), list):
            raise ValueError(f"OSRM table failed: {payload.get('code') or 'invalid response'}")
        result = _best_roundtrip_from_matrix(payload["distances"], valid_stops)
        if incomplete_coordinates:
            return RoutingResult(result.distance_km, "osrm_partial_coordinates", True, result.order)
        return result
    except Exception:
        result = _fallback_roundtrip(
            float(origin_lat),
            float(origin_lon),
            valid_stops,
            distance_factor=fallback_distance_factor,
        )
        if incomplete_coordinates:
            return RoutingResult(result.distance_km, "haversine_partial_coordinates", True, result.order)
        return result

import json

from app import routing
from app.routing import RoutingStop


class _Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_osrm_matrix_chooses_shortest_two_store_roundtrip(monkeypatch):
    # origin=0, A=1, B=2. O->B->A->O is shorter than O->A->B->O.
    matrix = [
        [0, 8000, 2000],
        [3000, 0, 9000],
        [7000, 1000, 0],
    ]
    monkeypatch.setattr(routing, "urlopen", lambda *_args, **_kwargs: _Response({"code": "Ok", "distances": matrix}))

    result = routing.optimized_roundtrip(
        50.0,
        7.0,
        [
            RoutingStop("A", 50.1, 7.1),
            RoutingStop("B", 50.2, 7.2),
        ],
        base_url="https://router.invalid",
        timeout_seconds=1,
        fallback_distance_factor=1.25,
    )

    assert result.distance_km == 6.0
    assert result.order == ("B", "A")
    assert result.source == "osrm"
    assert result.estimated is False


def test_road_distances_from_origin_uses_one_way_matrix(monkeypatch):
    matrix = [
        [0, 3500, 12100],
        [3600, 0, 8800],
        [11900, 8700, 0],
    ]
    monkeypatch.setattr(routing, "urlopen", lambda *_args, **_kwargs: _Response({"code": "Ok", "distances": matrix}))

    result = routing.road_distances_from_origin(
        50.0,
        7.0,
        [RoutingStop("edeka", 50.01, 7.01), RoutingStop("rewe", 50.02, 7.02)],
        base_url="https://router.invalid",
        timeout_seconds=1,
        fallback_distance_factor=1.25,
    )

    assert result == {"edeka": 3.5, "rewe": 12.1}


def test_road_distances_from_origin_falls_back_per_store(monkeypatch):
    monkeypatch.setattr(routing, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline")))
    result = routing.road_distances_from_origin(
        50.0,
        7.0,
        [RoutingStop("A", 50.01, 7.01)],
        base_url="https://router.invalid",
        timeout_seconds=1,
        fallback_distance_factor=1.25,
    )
    assert result["A"] > 0


def test_osrm_matrix_checks_all_three_store_permutations(monkeypatch):
    # Explicitly make O->C->B->A->O the unique cheapest tour (4 km).
    matrix = [
        [0, 9000, 9000, 1000],
        [1000, 0, 9000, 9000],
        [9000, 1000, 0, 9000],
        [9000, 9000, 1000, 0],
    ]
    monkeypatch.setattr(routing, "urlopen", lambda *_args, **_kwargs: _Response({"code": "Ok", "distances": matrix}))

    result = routing.optimized_roundtrip(
        50.0,
        7.0,
        [
            RoutingStop("A", 50.1, 7.1),
            RoutingStop("B", 50.2, 7.2),
            RoutingStop("C", 50.3, 7.3),
        ],
        base_url="https://router.invalid",
        timeout_seconds=1,
        fallback_distance_factor=1.25,
    )

    assert result.distance_km == 4.0
    assert result.order == ("C", "B", "A")


def test_routing_provider_failure_uses_haversine_fallback(monkeypatch):
    def fail(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr(routing, "urlopen", fail)
    result = routing.optimized_roundtrip(
        50.0,
        7.0,
        [RoutingStop("A", 50.01, 7.01)],
        base_url="https://router.invalid",
        timeout_seconds=1,
        fallback_distance_factor=1.25,
    )

    assert result.distance_km > 0
    assert result.source == "haversine_fallback"
    assert result.estimated is True
    assert result.order == ("A",)


def test_missing_user_coordinates_does_not_crash():
    result = routing.optimized_roundtrip(
        None,
        7.0,
        [RoutingStop("A", 50.01, 7.01)],
        base_url="https://router.invalid",
        timeout_seconds=1,
        fallback_distance_factor=1.25,
    )

    assert result.distance_km == 0
    assert result.source == "missing_coordinates"
    assert result.estimated is True


def test_no_stops_has_zero_distance():
    result = routing.optimized_roundtrip(
        50.0,
        7.0,
        [],
        base_url="https://router.invalid",
        timeout_seconds=1,
        fallback_distance_factor=1.25,
    )

    assert result.distance_km == 0
    assert result.source == "none"
    assert result.estimated is False

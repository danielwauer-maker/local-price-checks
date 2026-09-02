import json

from app import routing
from app.routing import RoutingStop


class _Response:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def read(self): return json.dumps(self.payload).encode("utf-8")


def test_optimized_roundtrip_exposes_each_road_leg(monkeypatch):
    matrix = [
        [0, 3500, 12100],
        [3600, 0, 8400],
        [12000, 8300, 0],
    ]
    monkeypatch.setattr(routing, "urlopen", lambda *_args, **_kwargs: _Response({"code": "Ok", "distances": matrix}))
    result = routing.optimized_roundtrip(
        50.0, 7.0,
        [RoutingStop("edeka", 50.01, 7.01), RoutingStop("rewe", 50.02, 7.02)],
        base_url="https://router.invalid", timeout_seconds=1, fallback_distance_factor=1.25,
    )
    assert result.order == ("edeka", "rewe")
    assert result.legs_km == (3.5, 8.4, 12.0)
    assert result.distance_km == 23.9
    assert sum(result.legs_km) == result.distance_km

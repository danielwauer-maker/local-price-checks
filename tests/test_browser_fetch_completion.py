from app.engine_v140.browser_fetch import _load_complete_surface


class _NoMatches:
    def count(self):
        return 0


class _FakePage:
    def __init__(self, signatures):
        self.signatures = list(signatures)
        self.signature_calls = 0
        self.wait_calls = 0

    def get_by_text(self, _label, exact=True):
        assert exact is True
        return _NoMatches()

    def wait_for_timeout(self, _milliseconds):
        self.wait_calls += 1

    def evaluate(self, script):
        if script.startswith("window.scrollTo"):
            return None
        index = min(self.signature_calls, len(self.signatures) - 1)
        self.signature_calls += 1
        return self.signatures[index]


def test_load_complete_surface_stops_after_two_stable_iterations():
    page = _FakePage([
        {"height": 1000, "offers": 20},
        {"height": 1000, "offers": 20},
        {"height": 1000, "offers": 20},
    ])

    _load_complete_surface(page)

    assert page.signature_calls == 3
    assert page.wait_calls == 3


def test_load_complete_surface_keeps_loading_while_offer_count_changes():
    page = _FakePage([
        {"height": 1000, "offers": 20},
        {"height": 1400, "offers": 40},
        {"height": 1800, "offers": 60},
        {"height": 1800, "offers": 60},
        {"height": 1800, "offers": 60},
    ])

    _load_complete_surface(page)

    assert page.signature_calls == 5


def test_load_complete_surface_honors_watchdog():
    page = _FakePage([{"height": index * 100, "offers": index} for index in range(1, 10)])

    _load_complete_surface(page, max_iterations=4)

    assert page.signature_calls == 4

from app.engine_v140.collectors import parse_rewe_text
from app.engine_v140.source_registry import RetailSource


def _source(name: str, market_id: str) -> RetailSource:
    return RetailSource(
        f"rewe_{market_id}",
        "REWE",
        name,
        f"https://www.rewe.de/angebote/test/{market_id}/markt/",
        "store_page",
        "store_specific",
        store_specific=True,
    )


def test_rewe_cards_prefer_product_title_over_descriptor_fragments_for_every_market():
    text = """
    Angebote gültig vom 17.08.2026 bis 22.08.2026
    Bifteki
    aus Rind- und Schweinefleisch, mit Käse
    je 100 g
    Aktion
    1,39 €
    Meisterschinken
    gegart
    je 100 g
    Aktion
    1,59 €
    Mars m&m’s
    Peanut
    je 150-g-Btl.
    Aktion
    1,79 €
    Mebus Wanduhr
    je 1 Stück
    Aktion
    9,99 €
    Funny-frisch Kessel Chips
    Sweet Chili & Red Pepper
    je 120-g-Btl.
    Aktion
    1,49 €
    """
    images = [
        {"url": "https://img.rewe.invalid/bifteki.jpg", "alt": "Bifteki"},
        {"url": "https://img.rewe.invalid/schinken.jpg", "alt": "Meisterschinken"},
        {"url": "https://img.rewe.invalid/mms.jpg", "alt": "Mars m&m’s Peanut"},
        {"url": "https://img.rewe.invalid/wanduhr.jpg", "alt": "Mebus Wanduhr"},
        {"url": "https://img.rewe.invalid/chips.jpg", "alt": "Funny-frisch Kessel Chips"},
        {"url": "https://img.rewe.invalid/jam.jpg", "alt": "Dittmann Chili Pepper Jam"},
    ]

    for name, market_id in (("REWE Hundertmark", "321019"), ("REWE Weirich", "1940425")):
        rows = parse_rewe_text(_source(name, market_id), text, images)
        assert [row.product_name for row in rows] == [
            "Bifteki",
            "Meisterschinken",
            "Mars m&m’s",
            "Mebus Wanduhr",
            "Funny-frisch Kessel Chips",
        ]
        assert all(row.image_url for row in rows)
        assert all(row.image_alt != "Dittmann Chili Pepper Jam" for row in rows)
        assert not any(row.product_name.lower() in {"peanut", "gegart", "je st."} for row in rows)

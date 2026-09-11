from app.aldi_live_collector import parse_aldi_stationary_chain_document
from app.engine_v140.source_registry import RetailSource


def _source():
    return RetailSource(
        key="aldi-structured-test",
        retailer="ALDI SÜD",
        store_name="ALDI SÜD Dierdorf",
        url="https://www.aldi-sued.de/angebote",
        mode="prospect_discovery",
        locality="regional_chain",
        notes="test",
        supports_products=True,
        store_specific=False,
    )


def _visible():
    return "Wochenangebote Mo., 7.9. – So., 13.9."


def test_structured_cards_keep_neighbor_products_isolated_and_use_card_image():
    html = """
    <html><body>
      <section class="offer-card">
        <div>Kühlung BBQ</div>
        <div>Rinder-Cevapcici 400 g</div>
        <div>0,4 kg (9,98 €/1 kg)</div>
        <div>Spare 24 % 3,99 € 5,29 €</div>
        <img src="/img/rinder.webp" alt="Rinder-Cevapcici 400 g">
      </section>
      <section class="offer-card">
        <div>Kühlung BBQ</div>
        <div>Hähnchenschenkel-Steaks 500 g, BBQ</div>
        <div>0,5 kg (6,58 €/1 kg)</div>
        <div>Spare 25 % 3,29 € 4,39 €</div>
        <img data-src="/img/huhn.webp" alt="Hähnchenschenkel-Steaks 500 g">
      </section>
    </body></html>
    """

    rows = parse_aldi_stationary_chain_document(_source(), html, _visible(), [])

    assert [(r.product_name, r.price, r.regular_price) for r in rows] == [
        ("Rinder-Cevapcici 400 g", 3.99, 5.29),
        ("Hähnchenschenkel-Steaks 500 g, BBQ", 3.29, 4.39),
    ]
    assert rows[0].source_text.count("Spare") == 1
    assert "Hähnchenschenkel" not in rows[0].source_text
    assert rows[0].image_url == "https://www.aldi-sued.de/img/rinder.webp"
    assert rows[1].image_url == "https://www.aldi-sued.de/img/huhn.webp"


def test_live_style_card_reconstructs_title_when_name_and_pack_are_split():
    html = """
    <html><body>
      <a class="product-card" href="/produkt/rinder-cevapcici">
        <span>Kühlung</span>
        <span>BBQ</span>
        <span>Rinder-Cevapcici</span>
        <span>400 g</span>
        <span>0,4 kg (9,98 €/1 kg)</span>
        <span>Spare 24 %</span><span>3,99 €</span><span>²</span><span>5,29 €</span>
        <img src="/img/rinder.webp" alt="Rinder-Cevapcici">
      </a>
      <a class="product-card" href="/produkt/putenbrust">
        <span>Kühlung</span>
        <span>MEINE METZGEREI</span>
        <span>Putenbrustfilet</span>
        <span>800 g</span>
        <span>0,8 kg (9,99 €/1 kg)</span>
        <span>Spare 20 %</span><span>7,99 €</span><span>²</span><span>9,99 €</span>
      </a>
    </body></html>
    """

    rows = parse_aldi_stationary_chain_document(_source(), html, _visible(), [])

    assert [(r.product_name, r.price, r.regular_price) for r in rows] == [
        ("BBQ Rinder-Cevapcici 400 g", 3.99, 5.29),
        ("MEINE METZGEREI Putenbrustfilet 800 g", 7.99, 9.99),
    ]
    assert rows[0].quantity == 400
    assert rows[0].unit == "g"
    assert rows[0].source_text.count("Spare") == 1
    assert "Putenbrust" not in rows[0].source_text


def test_structured_card_never_turns_deposit_into_offer_price():
    html = """
    <html><body>
      <article>
        <div>RIO D'ORO Orangennektar 1,5 l</div>
        <div>1,5 l (0,93 €/1 l)</div>
        <div>1,69 € + 0,25 € Pfand EINWEG</div>
        <div>Spare 17 % 1,39 € 1,69 €</div>
      </article>
    </body></html>
    """

    rows = parse_aldi_stationary_chain_document(_source(), html, _visible(), [])

    assert len(rows) == 1
    assert rows[0].product_name == "RIO D'ORO Orangennektar 1,5 l"
    assert rows[0].price == 1.39
    assert rows[0].regular_price == 1.69
    assert rows[0].price != 0.25


def test_structured_card_rejects_ambiguous_container_with_multiple_saving_pairs():
    html = """
    <html><body>
      <div>
        <span>Produkt A 200 g</span>
        <span>Spare 20 % 1,99 € 2,49 €</span>
        <span>Produkt B 300 g</span>
        <span>Spare 25 % 2,99 € 3,99 €</span>
      </div>
    </body></html>
    """

    rows = parse_aldi_stationary_chain_document(_source(), html, _visible(), [])

    assert rows == []

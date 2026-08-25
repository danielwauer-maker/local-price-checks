from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app.admin_seed import seed_admin_catalog
from app.category_classifier import ensure_auto_category
from app.db import Base, create_database_engine
from app.models import MasterProduct, ProductAdminData, ProductCategory
from app.product_search import search_products


def _catalog():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    seed_admin_catalog(db)
    products = [
        MasterProduct(name="ASC Lachsfilet", brand="Ocean Sea", normalized_key="asc-lachsfilet"),
        MasterProduct(name="15 Fischstäbchen", brand="Iglo", normalized_key="iglo-fischstaebchen"),
        MasterProduct(name="Thunfisch in eigenem Saft", brand="Saupiquet", normalized_key="thunfisch-saft"),
        MasterProduct(name="Coca-Cola Zero", brand="Coca-Cola", normalized_key="coca-cola-zero"),
        MasterProduct(name="Pepsi Max", brand="Pepsi", normalized_key="pepsi-max"),
        MasterProduct(name="Junger Gouda", brand="Milbona", normalized_key="junger-gouda"),
        MasterProduct(name="Büffel Mozzarella", brand="Galbani", normalized_key="bueffel-mozzarella"),
        MasterProduct(name="Pangasiusfilets", brand="Ocean Sea", normalized_key="pangasiusfilets"),
        MasterProduct(name="Schafkäse natur", brand="Milbona", normalized_key="schafkaese-natur"),
        MasterProduct(name="Vegane Salami", brand="Rügenwalder", normalized_key="vegane-salami"),
        MasterProduct(name="Kefir Drink", brand="MILRAM", normalized_key="kefir-drink"),
        MasterProduct(name="Corny Müsliriegel Schoko", brand="Corny", normalized_key="corny-muesliriegel"),
        MasterProduct(name="Müller Milch Reis", brand="Müller", normalized_key="mueller-milch-reis"),
        MasterProduct(name="Quarkbällchen", brand=None, normalized_key="quarkbaellchen"),
        MasterProduct(name="Butter Blätterteig", brand="Tante Fanny", normalized_key="butter-blaetterteig"),
        MasterProduct(name="Rahm-Spinat", brand="Iglo", normalized_key="iglo-rahm-spinat"),
        MasterProduct(name="Toilettenpapier", brand="Hakle", normalized_key="toilettenpapier"),
    ]
    db.add_all(products)
    db.flush()
    for row in products:
        ensure_auto_category(db, row)
    db.commit()
    return engine, db


def _names(db, query: str, category: str | None = None) -> list[str]:
    return [match.product.name for match in search_products(db, query=query, category_slug=category)]


def test_semantic_category_family_synonym_brand_and_partial_search():
    _, db = _catalog()

    assert {"ASC Lachsfilet", "15 Fischstäbchen", "Pangasiusfilets"}.issubset(_names(db, "Fisch"))
    assert "ASC Lachsfilet" in _names(db, "Lachs")
    assert {"Coca-Cola Zero", "Pepsi Max"}.issubset(_names(db, "Cola"))
    assert "Coca-Cola Zero" in _names(db, "Coke")
    assert {"Junger Gouda", "Büffel Mozzarella", "Schafkäse natur"}.issubset(_names(db, "Käse"))
    assert "Büffel Mozzarella" in _names(db, "Mozzarella")
    assert {"Coca-Cola Zero", "Pepsi Max"}.issubset(_names(db, "Getränke"))
    assert {"15 Fischstäbchen", "Rahm-Spinat"}.issubset(_names(db, "Iglo"))
    assert "Thunfisch in eigenem Saft" in _names(db, "Thun")
    assert "Toilettenpapier" not in _names(db, "Fisch")
    assert "ASC Lachsfilet" in _names(db, "", category="fisch")
    assert "Vegane Salami" in _names(db, "", category="vegetarisch-vegan")
    assert "Kefir Drink" in _names(db, "", category="molkerei")
    assert "Corny Müsliriegel Schoko" in _names(db, "", category="fruehstueck")
    assert "Müller Milch Reis" in _names(db, "", category="molkerei")
    assert {"Quarkbällchen", "Butter Blätterteig"}.issubset(_names(db, "", category="brot"))
    db.close()


def test_search_ranking_is_deterministic_and_query_count_is_bounded():
    engine, db = _catalog()
    exact = MasterProduct(name="Cola", brand="Test", normalized_key="exact-cola")
    db.add(exact)
    db.flush()
    ensure_auto_category(db, exact)
    db.commit()

    statements = 0

    def count_queries(*_args):
        nonlocal statements
        statements += 1

    event.listen(engine, "before_cursor_execute", count_queries)
    matches = search_products(db, query="Cola", limit=50)
    event.remove(engine, "before_cursor_execute", count_queries)

    assert matches[0].product.name == "Cola"
    assert [match.product.id for match in matches] == [match.product.id for match in search_products(db, query="Cola")]
    assert statements <= 3
    db.close()


def test_parent_search_includes_children_from_database_hierarchy():
    _, db = _catalog()
    drinks = db.query(ProductCategory).filter_by(slug="getraenke").one()
    cola = db.query(ProductCategory).filter_by(slug="cola").one()
    assert cola.parent_id == drinks.id
    cola_products = {
        row.product.name
        for row in db.query(ProductAdminData).filter(ProductAdminData.category_id == cola.id).all()
    }
    assert {"Coca-Cola Zero", "Pepsi Max"}.issubset(cola_products)
    assert cola_products.issubset(set(_names(db, "Getränke")))
    db.close()

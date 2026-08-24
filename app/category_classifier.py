from __future__ import annotations

from sqlalchemy.orm import Session

from .models import MasterProduct, ProductAdminData, ProductCategory

# Order matters: specific product families must win before broad ingredient words.
# The slugs intentionally mirror the frozen Lokero frontend category ids.
CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("fisch", (
        "fisch", "lachs", "thunfisch", "garnelen", "garnele", "forelle", "kabeljau", "seelachs", "matjes",
        "hering", "makrele", "dorade", "pangasius", "scampi", "meeresfrüchte", "fischstäbchen", "räucherlachs",
    )),
    ("kaese", (
        "käse", "gouda", "emmentaler", "mozzarella", "feta", "camembert", "brie", "parmesan", "grana padano",
        "bergkäse", "frischkäse", "hirtenkäse", "scheibenkäse", "reibekäse", "cheddar", "maasdamer",
    )),
    ("fleisch-wurst", (
        "fleisch", "rind", "schwein", "hähnchen", "huhn", "pute", "hack", "steak", "schnitzel", "braten",
        "wurst", "salami", "schinken", "speck", "würstchen", "bratwurst", "aufschnitt", "leberwurst", "mortadella",
        "frikadelle", "cevapcici", "gyros",
    )),
    ("fertiggerichte", (
        "fertiggericht", "fertigmenü", " fix ", "instant", "topfgericht", "eintopf", "air fryer", "pfannengericht",
        "lasagne", "ravioli", "maultaschen", "dosenravioli", "currywurst mit", "menü", "ready to eat",
    )),
    ("suesswaren", (
        "schokolade", "schoko", "keks", "kekse", "waffel", "bonbon", "gummi", "chips", "cracker", "nüsse", "nuss",
        "snack", "riegel", "praline", "lakritz", "popcorn", "fruchtgummi", "nachos", "salzstangen", "gebäck",
    )),
    ("getraenke", (
        "wasser", "quelle", "cola", "limonade", "limo", "saft", "nektar", "smoothie", "bier", "pils", "radler",
        "wein", "sekt", "prosecco", "vodka", "wodka", "whisky", " gin ", " rum ", "likör", "getränk", "energy",
        "eistee", "schorle", "sirup", "tonic", "orangeade", "helles", " hell ", "0,0%", "0.0%",
    )),
    ("brot", (
        "brot", "brötchen", "croissant", "baguette", "toast", "kuchen", "torte", "muffin", "donut", "backware",
        "brezel", "stuten", "ciabatta", "knäckebrot", "wrap", "tortilla",
    )),
    ("molkerei", (
        "milch", "joghurt", "jogurt", "almighurt", "froop", "ehrmann", "müller", "quark", "butter", "margarine",
        "sahne", "schmand", "kefir", "pudding", "milchreis", "skyr", "dessert", "eier", " ei ", "creme fraiche",
        "buttermilch", "ayran",
    )),
    ("obst-gemuese", (
        "apfel", "äpfel", "banane", "birne", "erdbe", "himbeer", "heidelbeer", "traube", "orange", "mandarine",
        "zitrone", "limette", "mango", "ananas", "kiwi", "melone", "pfirsich", "nektarine", "kirsche", "pflaume",
        "tomate", "gurke", "paprika", "kartoffel", "zwiebel", "knoblauch", "salat", "möhre", "karotte", "brokkoli",
        "blumenkohl", "zucchini", "aubergine", "champignon", "gemüse", "obst", "avocado", "radieschen", "spargel",
    )),
    ("fruehstueck", (
        "müsli", "haferflocken", "cornflakes", "cerealien", "marmelade", "konfitüre", "honig", "nuss-nougat",
        "frühstück", "kaffee", "espresso", "cappuccino", "kaffeebohnen", "filterkaffee", "tee ", "teebeutel",
    )),
    ("tiefkuehl", (
        "tiefkühl", "tiefgekühlt", " tk ", "pizza", "pommes", "eiscreme", "speiseeis", "stieleis", "eis am stiel",
        "tiefkühlgemüse", "backofen pommes",
    )),
    ("vorrat", (
        "nudel", "pasta", "reis", "mehl", "zucker", "salz", "öl", "essig", "konserve", "dose", "soße", "sauce",
        "ketchup", "senf", "mayonnaise", "mayo", "gewürz", "suppe", "brühe", "aufstrich", "tomatenmark", "pesto",
        "hülsenfrüchte", "bohnen", "linsen", "couscous", "bulgur", "backmischung", "hefe",
    )),
    ("drogerie", (
        "zahnpasta", "zahnbürste", "shampoo", "duschgel", "deo", "seife", "bodylotion", "hautcreme", "gesichtscreme",
        "windel", "tampon", "binde", "rasierer", "rasiergel", "haarspray", "haarfarbe", "mundspülung", "pflege",
    )),
    ("haushalt", (
        "waschmittel", "spülmittel", "reiniger", "toilettenpapier", "küchenrolle", "taschentücher", "müllbeutel", "haushalt",
        "geschirrspül", "allzweckreiniger", "weichspüler", "backpapier", "alufolie", "frischhaltefolie", "schwamm",
    )),
    ("tiernahrung", (
        "katzen", "katze", "hunde", "hund ", "tierfutter", "tier-nahrung", "hundefutter", "katzenfutter", "leckerl", "napf",
        "sheba", "whiskas", "pedigree", "felix", "purina",
    )),
]


def infer_category_slug(product: MasterProduct) -> str:
    # Spaces around the normalized haystack make phrase checks such as " fix " reliable.
    haystack = f" {' '.join(filter(None, [product.brand, product.name, product.package_size])).lower()} "
    for slug, keywords in CATEGORY_KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            return slug
    return "sonstiges"


def ensure_auto_category(db: Session, product: MasterProduct, *, force_unlocked: bool = False) -> ProductAdminData:
    meta = db.query(ProductAdminData).filter(ProductAdminData.master_product_id == product.id).first()
    if meta and meta.category_locked and meta.category_id is not None:
        return meta
    if not meta:
        meta = ProductAdminData(master_product_id=product.id)
        db.add(meta)
        db.flush()

    if meta.category_id is not None and not force_unlocked:
        current = db.get(ProductCategory, meta.category_id)
        if current and current.slug != "sonstiges" and current.active:
            return meta

    slug = infer_category_slug(product)
    category = db.query(ProductCategory).filter(ProductCategory.slug == slug, ProductCategory.active.is_(True)).first()
    if category:
        meta.category_id = category.id
    return meta


def backfill_auto_categories(db: Session, *, force_unlocked: bool = True) -> int:
    """Reclassify all non-locked products into the current Lokero taxonomy.

    Manual category corrections stay untouched. `force_unlocked=True` is important
    during taxonomy upgrades so products previously assigned to broad legacy
    categories are moved into the new store-like categories.
    """
    changed = 0
    products = db.query(MasterProduct).all()
    for product in products:
        before = db.query(ProductAdminData).filter(ProductAdminData.master_product_id == product.id).first()
        before_id = before.category_id if before else None
        meta = ensure_auto_category(db, product, force_unlocked=force_unlocked)
        if meta.category_id != before_id:
            changed += 1
    db.commit()
    return changed

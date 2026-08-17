from __future__ import annotations

from sqlalchemy.orm import Session

from .models import MasterProduct, ProductAdminData, ProductCategory

CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("backwaren", (
        "brot", "brötchen", "croissant", "baguette", "toast", "kuchen", "torte", "muffin", "donut", "backware", "brezel", "stuten",
    )),
    ("molkerei-kuehlung", (
        "milch", "joghurt", "jogurt", "almighurt", "froop", "ehrmann", "müller", "quark", "käse", "mozzarella", "feta", "butter", "margarine", "sahne", "schmand", "kefir", "pudding", "milchreis", "frischkäse", "skyr", "dessert", "eier", "ei ",
    )),
    ("obst-gemuese", (
        "apfel", "äpfel", "banane", "birne", "erdbe", "himbeer", "heidelbeer", "traube", "orange", "mandarine", "zitrone", "limette", "mango", "ananas", "kiwi", "melone", "pfirsich", "nektarine", "kirsche", "pflaume", "tomate", "gurke", "paprika", "kartoffel", "zwiebel", "knoblauch", "salat", "möhre", "karotte", "brokkoli", "blumenkohl", "zucchini", "aubergine", "champignon", "gemüse", "obst", "avocado",
    )),
    ("fleisch-fisch", (
        "fleisch", "rind", "schwein", "hähnchen", "huhn", "pute", "hack", "steak", "schnitzel", "braten", "wurst", "salami", "schinken", "speck", "würstchen", "bratwurst", "fisch", "lachs", "thunfisch", "garnelen", "forelle", "kabeljau", "seelachs",
    )),
    ("getraenke", (
        "wasser", "cola", "limonade", "limo", "saft", "nektar", "smoothie", "bier", "pils", "radler", "wein", "sekt", "prosecco", "vodka", "wodka", "whisky", "gin ", "rum ", "likör", "kaffee", "espresso", "cappuccino", "tee ", "getränk", "energy", "eistee",
    )),
    ("tiefkuehl", (
        "tiefkühl", "tk ", "pizza", "pommes", "eiscreme", "speiseeis", "eis ", "fischstäbchen",
    )),
    ("suesswaren-snacks", (
        "schokolade", "schoko", "keks", "kekse", "waffel", "bonbon", "gummi", "chips", "cracker", "nüsse", "nuss", "snack", "riegel", "praline", "lakritz", "popcorn",
    )),
    ("vorrat-grundnahrung", (
        "nudel", "pasta", "reis", "mehl", "zucker", "salz", "öl", "essig", "konserve", "dose", "müsli", "hafer", "cerealien", "cornflakes", "soße", "sauce", "ketchup", "senf", "mayonnaise", "mayo", "gewürz", "suppe", "brühe", "aufstrich", "marmelade", "honig",
    )),
    ("haushalt-drogerie", (
        "waschmittel", "spülmittel", "reiniger", "toilettenpapier", "küchenrolle", "zahnpasta", "zahnbürste", "shampoo", "duschgel", "deo", "seife", "creme", "windel", "taschentücher", "müllbeutel", "haushalt",
    )),
    ("tiernahrung", (
        "katzen", "hunde", "tierfutter", "tier-nahrung", "hundefutter", "katzenfutter", "leckerl", "napf",
    )),
]


def infer_category_slug(product: MasterProduct) -> str:
    haystack = " ".join(filter(None, [product.brand, product.name, product.package_size])).lower()
    for slug, keywords in CATEGORY_KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            return slug
    return "sonstiges"


def ensure_auto_category(db: Session, product: MasterProduct) -> ProductAdminData:
    meta = db.query(ProductAdminData).filter(ProductAdminData.master_product_id == product.id).first()
    if meta and meta.category_locked and meta.category_id is not None:
        return meta
    if not meta:
        meta = ProductAdminData(master_product_id=product.id)
        db.add(meta)
        db.flush()
    if meta.category_id is not None:
        current = db.get(ProductCategory, meta.category_id)
        if current and current.slug != "sonstiges":
            return meta
    slug = infer_category_slug(product)
    category = db.query(ProductCategory).filter(ProductCategory.slug == slug, ProductCategory.active.is_(True)).first()
    if category:
        meta.category_id = category.id
    return meta


def backfill_auto_categories(db: Session) -> int:
    changed = 0
    products = db.query(MasterProduct).all()
    for product in products:
        before = db.query(ProductAdminData).filter(ProductAdminData.master_product_id == product.id).first()
        before_id = before.category_id if before else None
        meta = ensure_auto_category(db, product)
        if meta.category_id != before_id:
            changed += 1
    db.commit()
    return changed

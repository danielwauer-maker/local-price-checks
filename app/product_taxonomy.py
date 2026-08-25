from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class CategorySpec:
    slug: str
    name: str
    sort_order: int
    parent_slug: str | None = None
    search_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaxonomyRule:
    slug: str
    terms: tuple[str, ...]
    reason: str
    compound_heads: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProductFamilySpec:
    slug: str
    label: str
    category_slugs: tuple[str, ...]
    terms: tuple[str, ...]


def normalize_search_text(value: str | None) -> str:
    folded = "".join(
        character
        for character in unicodedata.normalize("NFKD", (value or "").casefold())
        if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


def tokenize_search_text(value: str | None) -> tuple[str, ...]:
    """Return Unicode-folded tokens while treating hyphens as word separators."""

    return tuple(normalize_search_text(value).split())


def phrase_matches(value: str | None, phrase: str) -> bool:
    """Match a complete token or contiguous multi-token phrase.

    Single-word taxonomy terms never match arbitrary prefixes such as ``rum``
    in ``Rumpsteak``. Multi-word terms remain useful across punctuation, so
    ``Coca-Cola`` matches the normalized phrase ``coca cola``.
    """

    value_tokens = tokenize_search_text(value)
    phrase_tokens = tokenize_search_text(phrase)
    if not phrase_tokens or len(phrase_tokens) > len(value_tokens):
        return False
    width = len(phrase_tokens)
    return any(value_tokens[index:index + width] == phrase_tokens for index in range(len(value_tokens) - width + 1))


def taxonomy_term_matches(value: str | None, term: str) -> bool:
    """Match taxonomy and family terms only as complete normalized phrases."""

    return phrase_matches(value, term)


def compound_head_matches(value: str | None, head_term: str) -> bool:
    """Match an explicitly opted-in German compound head plus inflection.

    This is separate from normal term matching: only taxonomy rules that
    declare a known semantic head may use it. Thus ``Bierwurst`` can match the
    declared head ``wurst``, while the undeclared prefix ``bier`` cannot.
    """

    head_tokens = tokenize_search_text(head_term)
    if len(head_tokens) != 1:
        return False
    head = head_tokens[0]
    endings = (head, f"{head}e", f"{head}en", f"{head}n", f"{head}s")
    return any(token.endswith(endings) for token in tokenize_search_text(value))


def ingredient_list_matches(value: str | None) -> bool:
    """Recognize an ingredient-only fragment without guessing its product type.

    Production imports occasionally contain fragments such as ``mit Zwiebel,
    Gurke und Apfel`` instead of a product name.  Requiring the leading ``mit``
    plus at least two complete ingredient tokens keeps this guard narrow and
    prevents one listed ingredient from becoming the product category.
    """

    tokens = tokenize_search_text(value)
    if not tokens or tokens[0] != "mit":
        return False
    ingredients = {
        "apfel", "gurke", "karotte", "knoblauch", "mohre", "orange",
        "paprika", "tomate", "zwiebel",
    }
    return len(ingredients.intersection(tokens)) >= 2


def _category(slug: str, name: str, order: int, parent: str | None = None, *terms: str) -> CategorySpec:
    return CategorySpec(slug, name, order, parent, tuple(terms))


# Parent rows intentionally retain the established production slugs wherever
# possible. Seeding updates rows in place, preserving existing category ids and
# every authoritative ProductAdminData reference.
PRODUCT_TAXONOMY: tuple[CategorySpec, ...] = (
    _category("obst-gemuese", "Obst & Gemüse", 10, None, "frische produkte"),
    _category("obst", "Obst", 11, "obst-gemuese", "früchte", "frucht"),
    _category("gemuese", "Gemüse", 12, "obst-gemuese"),
    _category("salat", "Salat", 13, "obst-gemuese"),
    _category("kraeuter", "Kräuter", 14, "obst-gemuese"),
    _category("kartoffeln", "Kartoffeln", 15, "obst-gemuese"),
    _category("pilze", "Pilze", 16, "obst-gemuese", "champignons"),
    _category("fleisch-wurst", "Fleisch & Wurst", 20),
    _category("fleisch", "Fleisch", 21, "fleisch-wurst"),
    _category("gefluegel", "Geflügel", 22, "fleisch-wurst", "hähnchen", "pute"),
    _category("hackfleisch", "Hackfleisch", 23, "fleisch-wurst", "hack"),
    _category("wurst", "Wurst", 24, "fleisch-wurst"),
    _category("schinken", "Schinken", 25, "fleisch-wurst"),
    _category("grillfleisch", "Grillfleisch", 26, "fleisch-wurst"),
    _category("fisch", "Fisch & Meeresfrüchte", 30),
    _category("fisch-produkte", "Fisch", 31, "fisch", "frischfisch"),
    _category("raeucherfisch", "Räucherfisch", 32, "fisch", "räucherlachs"),
    _category("fischkonserven", "Fischkonserven", 33, "fisch", "thunfischdose"),
    _category("fisch-paniert", "Fischstäbchen & panierter Fisch", 34, "fisch", "fischstäbchen"),
    _category("meeresfruechte", "Meeresfrüchte", 35, "fisch", "garnelen", "scampi"),
    _category("kaese", "Käse", 40),
    _category("schnittkaese", "Schnittkäse", 41, "kaese", "gouda", "edamer"),
    _category("hartkaese", "Hartkäse", 42, "kaese", "parmesan", "emmentaler"),
    _category("weichkaese", "Weichkäse", 43, "kaese", "camembert", "brie"),
    _category("frischkaese", "Frischkäse", 44, "kaese"),
    _category("mozzarella", "Mozzarella", 45, "kaese"),
    _category("feta-hirtenkaese", "Feta & Hirtenkäse", 46, "kaese", "feta", "hirtenkäse"),
    _category("reibekaese", "Reibekäse", 47, "kaese", "geriebener käse"),
    _category("molkerei", "Milchprodukte", 50, None, "molkerei"),
    _category("milch", "Milch", 51, "molkerei", "vollmilch"),
    _category("joghurt", "Joghurt", 52, "molkerei", "yoghurt", "jogurt"),
    _category("quark", "Quark", 53, "molkerei"),
    _category("sahne", "Sahne", 54, "molkerei", "schmand"),
    _category("butter", "Butter", 55, "molkerei"),
    _category("molkerei-dessert", "Dessert", 56, "molkerei", "pudding", "milchreis"),
    _category("brot", "Brot & Backwaren", 60),
    _category("brot-produkte", "Brot", 61, "brot"),
    _category("broetchen", "Brötchen", 62, "brot", "semmel"),
    _category("toast", "Toast", 63, "brot"),
    _category("kuchen", "Kuchen", 64, "brot", "torte"),
    _category("gebaeck", "Gebäck", 65, "brot", "croissant", "keks"),
    _category("backzutaten", "Backzutaten", 66, "brot", "backmischung", "hefe"),
    _category("fruehstueck", "Frühstück", 70),
    _category("muesli", "Müsli", 71, "fruehstueck", "haferflocken"),
    _category("cornflakes", "Cornflakes", 72, "fruehstueck", "cerealien"),
    _category("brotaufstrich", "Brotaufstrich", 73, "fruehstueck"),
    _category("honig", "Honig", 74, "fruehstueck"),
    _category("marmelade", "Marmelade", 75, "fruehstueck", "konfitüre"),
    _category("getraenke", "Getränke", 80),
    _category("wasser", "Wasser", 81, "getraenke", "mineralwasser", "sprudel"),
    _category("limonade", "Limonade", 82, "getraenke", "limo", "fanta", "sprite"),
    _category("cola", "Cola", 83, "getraenke", "coca cola", "coke", "pepsi"),
    _category("energy", "Energy", 84, "getraenke", "energydrink"),
    _category("saft", "Saft", 85, "getraenke", "nektar"),
    _category("eistee", "Eistee", 86, "getraenke", "ice tea"),
    _category("kaffee", "Kaffee", 87, "getraenke", "espresso"),
    _category("tee", "Tee", 88, "getraenke", "teebeutel"),
    _category("alkohol", "Alkoholische Getränke", 90),
    _category("bier", "Bier", 91, "alkohol", "pils", "radler"),
    _category("wein", "Wein", 92, "alkohol"),
    _category("sekt", "Sekt", 93, "alkohol", "prosecco"),
    _category("spirituosen", "Spirituosen", 94, "alkohol", "vodka", "whisky", "gin", "rum"),
    _category("suesswaren", "Süßwaren & Snacks", 100),
    _category("schokolade", "Schokolade", 101, "suesswaren", "pralinen"),
    _category("bonbons", "Bonbons", 102, "suesswaren", "fruchtgummi"),
    _category("kekse", "Kekse", 103, "suesswaren", "waffeln"),
    _category("chips", "Chips", 104, "suesswaren", "nachos"),
    _category("nuesse", "Nüsse", 105, "suesswaren"),
    _category("eis", "Eis", 106, "suesswaren", "eiscreme", "speiseeis"),
    _category("tiefkuehl", "Tiefkühl", 110, None, "tiefgekühlt", "tk"),
    _category("tiefkuehlpizza", "Tiefkühlpizza", 111, "tiefkuehl", "pizza"),
    _category("tiefkuehlgemuese", "Tiefkühlgemüse", 112, "tiefkuehl"),
    _category("tiefkuehlgerichte", "Tiefkühlgerichte", 113, "tiefkuehl"),
    _category("tiefkuehlfisch", "Tiefkühlfisch", 114, "tiefkuehl"),
    _category("fertiggerichte", "Fertiggerichte", 120),
    _category("konserven", "Konserven", 121, "fertiggerichte", "dose"),
    _category("suppen", "Suppen", 122, "fertiggerichte", "eintopf"),
    _category("instantgerichte", "Instantgerichte", 123, "fertiggerichte", "fix"),
    _category("fertigmenues", "Fertiggerichte & Menüs", 124, "fertiggerichte", "fertigmenü"),
    _category("fertigsaucen", "Fertigsaucen", 125, "fertiggerichte", "soße"),
    _category("nudeln-reis", "Nudeln, Reis & Beilagen", 130),
    _category("nudeln", "Nudeln", 131, "nudeln-reis", "pasta"),
    _category("reis", "Reis", 132, "nudeln-reis"),
    _category("kartoffelprodukte", "Kartoffelprodukte", 133, "nudeln-reis", "pommes"),
    _category("huelsenfruechte", "Hülsenfrüchte", 134, "nudeln-reis", "linsen", "bohnen"),
    _category("kochen-wuerzen", "Kochen & Würzen", 140),
    _category("oel", "Öl", 141, "kochen-wuerzen"),
    _category("essig", "Essig", 142, "kochen-wuerzen"),
    _category("gewuerze", "Gewürze", 143, "kochen-wuerzen"),
    _category("salz", "Salz", 144, "kochen-wuerzen"),
    _category("zucker", "Zucker", 145, "kochen-wuerzen"),
    _category("mehl", "Mehl", 146, "kochen-wuerzen"),
    _category("saucen", "Saucen", 147, "kochen-wuerzen", "ketchup", "senf"),
    _category("vegetarisch-vegan", "Vegetarisch & Vegan", 150),
    _category("fleischersatz", "Fleischersatz", 151, "vegetarisch-vegan"),
    _category("pflanzendrinks", "Pflanzendrinks", 152, "vegetarisch-vegan", "haferdrink", "sojadrink"),
    _category("vegane-produkte", "Vegane Produkte", 153, "vegetarisch-vegan"),
    _category("baby-kind", "Baby & Kind", 160),
    _category("babynahrung", "Babynahrung", 161, "baby-kind"),
    _category("kindergetraenke", "Kindergetränke", 162, "baby-kind"),
    _category("windeln", "Windeln", 163, "baby-kind"),
    _category("haushalt", "Haushalt", 170),
    _category("waschmittel", "Waschmittel", 171, "haushalt"),
    _category("reinigungsmittel", "Reinigungsmittel", 172, "haushalt", "reiniger"),
    _category("spuelmittel", "Spülmittel", 173, "haushalt"),
    _category("papierwaren", "Papierwaren", 174, "haushalt", "toilettenpapier", "küchenrolle"),
    _category("muellbeutel", "Müllbeutel", 175, "haushalt"),
    _category("drogerie", "Drogerie & Pflege", 180),
    _category("shampoo", "Shampoo", 181, "drogerie"),
    _category("duschgel", "Duschgel", 182, "drogerie"),
    _category("zahnpflege", "Zahnpflege", 183, "drogerie", "zahnpasta", "zahnbürste"),
    _category("deo", "Deo", 184, "drogerie"),
    _category("rasur", "Rasur", 185, "drogerie", "rasierer"),
    _category("hygiene", "Hygiene", 186, "drogerie", "tampon", "binde"),
    _category("tiernahrung", "Tierbedarf", 190),
    _category("hundefutter", "Hundefutter", 191, "tiernahrung"),
    _category("katzenfutter", "Katzenfutter", 192, "tiernahrung"),
    _category("tierzubehoer", "Tierzubehör", 193, "tiernahrung", "napf", "leine"),
    _category("non-food", "Non-Food", 200),
    _category("kuechenartikel", "Küchenartikel", 201, "non-food"),
    _category("textilien", "Textilien", 202, "non-food"),
    _category("elektronik", "Elektronik", 203, "non-food"),
    _category("aktionsware", "Aktionsware", 204, "non-food"),
    _category("sonstiges", "Sonstiges", 999),
)

CATEGORY_BY_SLUG = {category.slug: category for category in PRODUCT_TAXONOMY}


# Rules are one deliberately ordered engine: reliable product types and context
# precede ingredients/flavours, which precede broad tokens. Uncertain products
# deliberately fall back to unknown instead of receiving a forced assignment.
CLASSIFICATION_RULES: tuple[TaxonomyRule, ...] = (
    # Product-type and context rules. Their reason strings are also surfaced by
    # the reclassification dry run, so precedence decisions remain auditable.
    TaxonomyRule("pflanzendrinks", ("haferdrink", "hafermilch", "sojadrink", "sojamilch", "mandeldrink", "pflanzendrink"), "Pflanzendrink"),
    TaxonomyRule("fleischersatz", ("fleischersatz", "fleischalternative", "vegane fleischalternative", "vegetarische fleischalternative", "veganes steak", "vegetarisches steak", "veganes schnitzel", "vegetarisches schnitzel", "vegane wurst", "vegetarische wurst", "likemeat"), "veganer/vegetarischer Fleischersatz hat Vorrang vor Fleischbegriffen"),
    TaxonomyRule("katzenfutter", ("katzenfutter", "katzennahrung", "sheba", "whiskas", "felix"), "Katzenfutter hat Vorrang vor enthaltenen Tierarten"),
    TaxonomyRule("hundefutter", ("hundefutter", "hundenahrung", "pedigree", "cesar"), "Hundefutter hat Vorrang vor enthaltenen Tierarten"),
    TaxonomyRule("tiernahrung", ("tiernahrung", "tierfutter", "vitakraft"), "Tiernahrung hat Vorrang vor enthaltenen Tierarten"),
    TaxonomyRule("zahnpflege", ("zahnpasta", "zahnburste", "mundspulung", "zahnfleisch", "sensodyne", "proschmelz"), "Zahnpflege-Produkttyp"),
    TaxonomyRule("fisch-paniert", ("fischstabchen", "backfisch", "panierter fisch", "fischfilet paniert"), "panierter Fisch"),
    TaxonomyRule("fischkonserven", ("thunfisch", "sardinen", "fischkonserve"), "Fischkonserve"),
    TaxonomyRule("raeucherfisch", ("raucherlachs", "raucherfisch", "matjes", "matjesfilet", "matjesfilets", "rauchforelle"), "Räucherfisch"),
    TaxonomyRule("meeresfruechte", ("garnele", "garnelen", "scampi", "meeresfruchte", "muscheln", "calamari"), "Meeresfrüchte"),
    TaxonomyRule("fisch-produkte", ("lachs", "lachsfilet", "lachsfilets", "seelachs", "kabeljau", "forelle", "hering", "heringsfilet", "heringsfilets", "makrele", "dorade", "pangasius", "pangasiusfilet", "pangasiusfilets", "rotbarsch", "rotbarschfilet", "rotbarschfilets", "fisch"), "eindeutiger Fisch-Produkttyp"),
    TaxonomyRule("frischkaese", ("frischkase", "frischkasecreme", "cream cheese", "bresso", "miree"), "Frischkäse-Produkttyp hat Vorrang vor Kräutern"),
    TaxonomyRule("mozzarella", ("mozzarella",), "Mozzarella"),
    TaxonomyRule("feta-hirtenkaese", ("feta", "hirtenkase", "salatkase", "schafkase"), "Feta/Hirtenkäse"),
    TaxonomyRule("reibekaese", ("reibekase", "geriebener kase", "gratinkase"), "Reibekäse"),
    TaxonomyRule("weichkaese", ("camembert", "brie", "weichkase", "geramont"), "Weichkäse"),
    TaxonomyRule("hartkaese", ("parmesan", "grana padano", "bergkase", "hartkase", "emmentaler", "grillkase"), "Hartkäse"),
    TaxonomyRule("schnittkaese", ("gouda", "edamer", "maasdamer", "cheddar", "schnittkase", "scheibenkase", "kasescheibe", "kasescheiben"), "Schnittkäse"),
    TaxonomyRule("kaese", ("kase", "kaseprodukt"), "eindeutiger Käse-Produkttyp"),
    TaxonomyRule("tiefkuehlpizza", ("tiefkuhlpizza", "tk pizza", "pizza", "steinofen pizza", "steinofenpizza", "flammkuchen"), "Pizza/Fertiggericht hat Vorrang vor Belag oder Wortbestandteilen"),
    TaxonomyRule("tiefkuehlgerichte", ("tiefkuhlgericht", "tk gericht", "butter chicken", "frosta butter chicken"), "Tiefkühl-/Fertiggericht hat Vorrang vor Zutaten"),
    TaxonomyRule("instantgerichte", ("fertiggericht", "fertigmenu", "instant", "knorr fix", "maggi fix", "air fryer", "dosenravioli"), "Instant-/Fertiggericht hat Vorrang vor Zutaten"),
    TaxonomyRule("fertigmenues", ("lasagne", "ravioli", "maultaschen", "pfannengericht", "menu"), "Fertiggericht hat Vorrang vor Zutaten"),
    TaxonomyRule("chips", ("chips", "nachos", "salzstangen", "cracker"), "salziger Snack hat Vorrang vor Geschmacksrichtung"),
    TaxonomyRule("schokolade", ("schokolade", "milchschokolade", "schoko", "schokostabchen", "praline", "ritter sport"), "Schokolade/Süßware hat Vorrang vor Aroma oder Zutat"),
    TaxonomyRule("bonbons", ("bonbon", "fruchtgummi", "lakritz", "gummibarchen"), "Bonbons/Fruchtgummi"),
    TaxonomyRule("kekse", ("keks", "waffel", "jaffa cake"), "Keks/Süßware hat Vorrang vor Fruchtgeschmack"),
    TaxonomyRule("nuesse", ("nusse", "nussmix", "erdnusse"), "Nüsse"),
    TaxonomyRule("eis", ("eiscreme", "speiseeis", "stieleis", "eis am stiel"), "Speiseeis"),
    TaxonomyRule("muesli", ("musli", "haferflocken", "musliriegel"), "Müsli-/Riegel-Produkttyp hat Vorrang vor Zutaten"),
    TaxonomyRule("saucen", ("ketchup", "senf", "mayonnaise", "mayo", "sauce", "sosse", "dressing", "salat kronung"), "Sauce/Dressing hat Vorrang vor enthaltenem Obst oder Gemüse"),
    TaxonomyRule("gebaeck", ("croissant", "buttercroissant"), "Gebäck hat Vorrang vor Zutaten"),

    # Beverages are explicit product descriptions, never substrings.
    TaxonomyRule("cola", ("coca cola", "coca-cola", "coke", "pepsi", "afri cola", "fritz cola", "freeway cola", "cola"), "Cola-Familie"),
    TaxonomyRule("energy", ("energy drink", "energydrink", "red bull", "monster energy"), "Energy-Drink"),
    TaxonomyRule("eistee", ("eistee", "ice tea"), "Eistee"),
    TaxonomyRule("limonade", ("fanta", "sprite", "limonade", "orangeade", "limo"), "Limonade"),
    TaxonomyRule("wasser", ("mineralwasser", "wasser", "sprudel", "quelle"), "Wasser"),
    TaxonomyRule("saft", ("saft", "nektar", "smoothie", "schorle"), "Saft"),
    TaxonomyRule("kaffee", ("kaffee", "espresso", "cappuccino", "kaffeebohnen"), "Kaffee"),
    TaxonomyRule("tee", ("teebeutel", "schwarztee", "gruntee", "krautertee"), "Tee"),
    TaxonomyRule("bier", ("bier", "pils", "pilsener", "radler", "helles", "lagerbier", "exportbier", "weizenbier", "weissbier", "bockbier", "kellerbier", "schmackes hell", "0 0 hell"), "eindeutige Bierbezeichnung"),
    TaxonomyRule("sekt", ("sekt", "prosecco", "champagner"), "Sekt"),
    TaxonomyRule("spirituosen", ("vodka", "wodka", "whisky", "whiskey", "gin", "rum", "likor", "korn", "ouzo", "tequila", "brandy", "cognac", "schnaps"), "eindeutige Spirituosenbezeichnung"),
    TaxonomyRule("wein", ("rotwein", "weisswein", "rosewein", "wein", "riesling", "grauburgunder", "weissburgunder", "spatburgunder", "dornfelder", "chardonnay"), "eindeutige Weinbezeichnung"),

    # Dairy and meat follow prepared-product contexts so ingredients and
    # toppings cannot take over the category.
    TaxonomyRule("joghurt", ("joghurt", "jogurt", "yoghurt", "almighurt", "froop"), "Joghurt"),
    TaxonomyRule("quark", ("quark", "skyr"), "Quark"),
    TaxonomyRule("sahne", ("sahne", "schmand", "creme fraiche", "kefir"), "Sahneprodukt"),
    TaxonomyRule("butter", ("butter", "margarine"), "Butter/Streichfett"),
    TaxonomyRule("molkerei-dessert", ("pudding", "milchreis", "molkereidessert"), "Molkereidessert"),
    TaxonomyRule("milch", ("vollmilch", "fettarme milch", "buttermilch", "milch"), "Milch"),
    TaxonomyRule("tiefkuehlgemuese", ("tiefkuhlgemuse", "tk gemuse"), "Tiefkühlgemüse"),
    TaxonomyRule("tiefkuehlfisch", ("tiefkuhlfisch", "tk fisch"), "Tiefkühlfisch"),
    TaxonomyRule("gefluegel", ("hahnchen", "huhn", "pute", "geflugel"), "Geflügel"),
    TaxonomyRule("hackfleisch", ("hackfleisch", "rinderhack", "hack"), "Hackfleisch"),
    TaxonomyRule("schinken", ("schinken", "speck"), "Schinken"),
    TaxonomyRule("wurst", ("wurst", "salami", "bratwurst", "aufschnitt", "mortadella"), "Wurst", ("wurst",)),
    TaxonomyRule("grillfleisch", ("grillfleisch", "grillsteak", "cevapcici", "grillspies"), "Grillfleisch"),
    TaxonomyRule("fleisch", ("fleisch", "rindfleisch", "schweinefleisch", "rind", "schwein", "steak", "schnitzel", "braten"), "Fleisch", ("steak", "schnitzel", "braten")),
    TaxonomyRule("gebaeck", ("croissant", "geback", "donut", "muffin"), "Gebäck"),
    TaxonomyRule("toast", ("toast",), "Toast"),
    TaxonomyRule("broetchen", ("brotchen", "semmel", "baguette", "brezel", "ciabatta"), "Brötchen/kleine Backware"),
    TaxonomyRule("kuchen", ("kuchen", "torte"), "Kuchen"),
    TaxonomyRule("backzutaten", ("backmischung", "hefe", "backpulver"), "Backzutat"),
    TaxonomyRule("brot-produkte", ("brot", "knackebrot"), "Brot"),
    TaxonomyRule("cornflakes", ("cornflakes", "cerealien"), "Cornflakes"),
    TaxonomyRule("marmelade", ("marmelade", "konfiture"), "Marmelade"),
    TaxonomyRule("honig", ("honig",), "Honig"),
    TaxonomyRule("brotaufstrich", ("brotaufstrich", "nuss nougat", "nuss-nougat"), "Brotaufstrich"),
    TaxonomyRule("suppen", ("suppe", "eintopf", "bruhe"), "Suppe/Eintopf"),
    TaxonomyRule("konserven", ("konserve", "dose"), "Konserve"),
    TaxonomyRule("nudeln", ("nudel", "pasta", "spaghetti", "penne"), "Nudeln"),
    TaxonomyRule("reis", ("reis", "couscous", "bulgur"), "Reis/Beilage"),
    TaxonomyRule("kartoffelprodukte", ("pommes", "kroketten", "kartoffelpuree"), "Kartoffelprodukt"),
    TaxonomyRule("huelsenfruechte", ("linsen", "bohnen", "hulsenfruchte"), "Hülsenfrucht"),
    # Produce requires explicit singular/plural product tokens. Ingredient-only
    # fragments are rejected by ``ingredient_list_matches`` before this stage.
    TaxonomyRule("pilze", ("champignon", "champignons", "pilz", "pilze", "pfifferling", "pfifferlinge"), "Pilz-Grundprodukt"),
    TaxonomyRule("kartoffeln", ("kartoffel",), "Kartoffel"),
    TaxonomyRule("salat", ("salat",), "Salat"),
    TaxonomyRule("kraeuter", ("krauter", "basilikum", "petersilie", "schnittlauch"), "Kräuter"),
    TaxonomyRule("obst", ("apfel", "banane", "bananen", "birne", "birnen", "erdbeere", "erdbeeren", "traube", "trauben", "weintraube", "weintrauben", "orange", "orangen", "mango", "mangos", "ananas", "kiwi", "kiwis", "melone", "melonen", "zitrone", "zitronen", "nektarine", "nektarinen", "zwetschge", "zwetschgen"), "Obst-Grundprodukt", ("apfel", "beere", "traube")),
    TaxonomyRule("gemuese", ("tomate", "tomaten", "gurke", "gurken", "paprika", "zwiebel", "zwiebeln", "knoblauch", "mohre", "mohren", "karotte", "karotten", "brokkoli", "blumenkohl", "zucchini", "aubergine", "gemuse", "chicoree"), "Gemüse-Grundprodukt"),
    TaxonomyRule("babynahrung", ("babynahrung", "babybrei", "quetschie"), "Babynahrung"),
    TaxonomyRule("windeln", ("windel", "pampers"), "Windeln"),
    TaxonomyRule("waschmittel", ("waschmittel", "weichspuler"), "Waschmittel"),
    TaxonomyRule("spuelmittel", ("spulmittel", "geschirrspul"), "Spülmittel"),
    TaxonomyRule("papierwaren", ("toilettenpapier", "kuchenrolle", "taschentucher"), "Papierware"),
    TaxonomyRule("muellbeutel", ("mullbeutel",), "Müllbeutel"),
    TaxonomyRule("reinigungsmittel", ("reiniger", "putzmittel"), "Reinigungsmittel"),
    TaxonomyRule("shampoo", ("shampoo",), "Shampoo"),
    TaxonomyRule("duschgel", ("duschgel",), "Duschgel"),
    TaxonomyRule("deo", ("deodorant", "deo"), "Deo"),
    TaxonomyRule("rasur", ("rasierer", "rasiergel"), "Rasur"),
    TaxonomyRule("hygiene", ("tampon", "binde", "hygiene"), "Hygiene"),
    TaxonomyRule("oel", ("olivenol", "sonnenblumenol", "speiseol"), "Öl"),
    TaxonomyRule("essig", ("essig",), "Essig"),
    TaxonomyRule("gewuerze", ("gewurz",), "Gewürz"),
    TaxonomyRule("salz", ("salz",), "Salz"),
    TaxonomyRule("zucker", ("zucker",), "Zucker"),
    TaxonomyRule("mehl", ("mehl",), "Mehl"),
)


PRODUCT_FAMILY_SPECS: tuple[ProductFamilySpec, ...] = (
    ProductFamilySpec("cola", "Cola", ("cola",), ("cola", "coca cola", "coca-cola", "coke", "pepsi", "pepsi cola", "afri cola", "fritz cola", "freeway cola")),
    ProductFamilySpec("wasser", "Wasser", ("wasser",), ("wasser", "mineralwasser", "sprudel")),
    ProductFamilySpec("bier", "Bier", ("bier",), ("bier", "pils", "radler", "helles")),
    ProductFamilySpec("fisch", "Fisch", ("fisch", "fisch-produkte", "raeucherfisch", "fischkonserven", "fisch-paniert", "meeresfruechte", "tiefkuehlfisch"), ("fisch", "lachs", "lachsfilet", "seelachs", "kabeljau", "thunfisch", "forelle", "hering", "matjes", "makrele", "fischstabchen", "raucherlachs")),
    ProductFamilySpec("kaese", "Käse", ("kaese", "schnittkaese", "hartkaese", "weichkaese", "frischkaese", "mozzarella", "feta-hirtenkaese", "reibekaese"), ("kase", "gouda", "edamer", "emmentaler", "parmesan", "mozzarella", "camembert", "brie", "feta", "hirtenkase", "frischkase")),
    ProductFamilySpec("milch", "Milch", ("milch",), ("milch", "vollmilch", "fettarme milch")),
    ProductFamilySpec("butter", "Butter", ("butter",), ("butter", "margarine")),
    ProductFamilySpec("kaffee", "Kaffee", ("kaffee",), ("kaffee", "espresso", "cappuccino")),
    ProductFamilySpec("joghurt", "Joghurt", ("joghurt",), ("joghurt", "jogurt", "yoghurt")),
    ProductFamilySpec("chips", "Chips", ("chips",), ("chips", "crisps", "nachos")),
    ProductFamilySpec("schokolade", "Schokolade", ("schokolade",), ("schokolade", "schoko", "pralinen")),
    ProductFamilySpec("katzenfutter", "Katzenfutter", ("katzenfutter",), ("katzenfutter", "katze", "sheba", "whiskas", "felix")),
    ProductFamilySpec("hundefutter", "Hundefutter", ("hundefutter",), ("hundefutter", "hund", "pedigree", "cesar")),
)

FAMILY_BY_SLUG = {family.slug: family for family in PRODUCT_FAMILY_SPECS}


def category_ancestor_slugs(slug: str | None) -> tuple[str, ...]:
    result: list[str] = []
    current = CATEGORY_BY_SLUG.get(slug or "")
    while current is not None:
        result.append(current.slug)
        current = CATEGORY_BY_SLUG.get(current.parent_slug or "")
    return tuple(result)


def root_category_slug(slug: str | None) -> str:
    ancestors = category_ancestor_slugs(slug)
    return ancestors[-1] if ancestors else "sonstiges"


def category_descendant_slugs(slug: str) -> set[str]:
    result = {slug}
    changed = True
    while changed:
        changed = False
        for category in PRODUCT_TAXONOMY:
            if category.parent_slug in result and category.slug not in result:
                result.add(category.slug)
                changed = True
    return result


def matching_family(value: str, category_slug: str | None = None) -> ProductFamilySpec | None:
    ancestors = set(category_ancestor_slugs(category_slug))
    for family in PRODUCT_FAMILY_SPECS:
        if ancestors.intersection(family.category_slugs):
            return family
        if any(taxonomy_term_matches(value, term) for term in family.terms):
            return family
    return None


def public_product_families() -> list[dict[str, object]]:
    return [
        {
            "slug": family.slug,
            "label": family.label,
            "category": root_category_slug(family.category_slugs[0]),
            "keywords": list(family.terms),
        }
        for family in PRODUCT_FAMILY_SPECS
    ]

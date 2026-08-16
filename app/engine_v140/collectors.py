from dataclasses import dataclass

CATS=[
("Kekse & Gebäck",["butterkeks","keks","cookies","soft cake","cheez-it"]),
("Kochen & Würzen",["maggi fix","fix air fryer","würzmix","würz","sauce","soße"]),
("Kaffee",["kaffee","krönung","espresso","prodomo"]),
("Käse",["weichkäse","gouda","patros","grünländer","geramont","géramont"]),
("Joghurt",["joghurt","sahnejoghurt"]),
("Süßwaren",["haribo","milka","snickers","twix","mr. tom","fruchtgummi"]),
("Bier",["pilsener","bier","veltins"]),
("Spirituosen",["gin","whisky","whiskey","rum","havana club","johnnie walker","aperol","sarti rosa"]),
("Wein & Sekt",["sekt","crémant","cremant","wein"]),
("Tiefkühl",["tiefgefroren","frosta","iglo","ofenfrische"]),
("Getränke",["wasser","tee","energy","valensina","schweppes","saft"]),
]

@dataclass
class CollectedOffer:
    source_key:str
    store_name:str
    retailer:str
    product_name:str
    category:str
    price:float|None
    regular_price:float|None=None
    app_price:float|None=None
    unit_price:float|None=None
    unit_price_unit:str|None=None
    quantity:float|None=None
    unit:str|None=None
    valid_from:str|None=None
    valid_to:str|None=None
    source_text:str=""
    source_url:str=""
    image_url:str|None=None
    image_alt:str|None=None
    local_store_offer:bool=True
    confidence:float=.5

def cat(s):
    x=(s or '').lower()
    for c,words in CATS:
        if any(w in x for w in words):
            return c
    return "Sonstiges"

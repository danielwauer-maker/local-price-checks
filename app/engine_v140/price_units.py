from __future__ import annotations

def canonical_unit_price_unit(product_unit: str | None) -> str | None:
    if not product_unit:
        return None
    u=product_unit.lower().strip().replace("stk.","stück").replace("stk","stück")
    if u in {"g","kg"}: return "kg"
    if u in {"ml","l"}: return "l"
    if u in {"stück","st"}: return "Stück"
    return u

def normalize_unit_price(value: float | None, source_unit: str | None, product_unit: str | None):
    if value is None: return None, canonical_unit_price_unit(product_unit)
    su=(source_unit or "").lower().replace(" ","")
    if su in {"100g","100 g"}: return round(value*10,4),"kg"
    if su in {"100ml","100 ml"}: return round(value*10,4),"l"
    if su in {"kg","1kg"}: return value,"kg"
    if su in {"l","1l"}: return value,"l"
    if su in {"stück","st"}: return value,"Stück"
    return value,canonical_unit_price_unit(product_unit)

def compute_unit_price(price: float | None, quantity: float | None, unit: str | None):
    if price is None or quantity is None or not unit or quantity<=0: return None,None
    u=unit.lower().strip(); q=float(quantity)
    if u=="g": return round(price/(q/1000),4),"kg"
    if u=="kg": return round(price/q,4),"kg"
    if u=="ml": return round(price/(q/1000),4),"l"
    if u=="l": return round(price/q,4),"l"
    if u in {"stück","stk","stk."}: return round(price/q,4),"Stück"
    return None,None

def packaging_label(quantity: float | None, unit: str | None) -> str:
    if quantity is None or not unit: return "Packungsgröße unbekannt"
    q=float(quantity); shown=int(q) if q.is_integer() else str(q).replace(".",",")
    u=unit.replace("stk.","Stück").replace("stk","Stück")
    return f"{shown} {u}"

def unit_price_label(value: float | None, unit: str | None) -> str:
    if value is None: return "Grundpreis nicht verfügbar"
    u=unit or "Einheit"
    return f"{value:.2f} €/{u}".replace(".",",")

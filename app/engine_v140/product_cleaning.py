from __future__ import annotations
import re

NAVIGATION_MARKERS=("bereich überspringen","zu den angeboten","aktuelle prospekte","filialen in der nähe","stellenangebote für die filiale")
ORIGIN_PREFIX=re.compile(r"^(?:Japan|Frankreich(?:\s*/\s*Luxemburg)?|Italien|Spanien|Portugal|Griechenland|Österreich)\s*[-–:]\s*",re.I)

def normalize_known_product_name(text:str)->str:
    t=(text or "").strip(); t=ORIGIN_PREFIX.sub("",t)
    if re.match(r"^ramont\s+weichkäse\b",t,re.I): t=re.sub(r"^ramont\b","Géramont",t,flags=re.I)
    return t

BAD_EXACT={"filiale","filiale & shop","aktion","knaller","angebote","angebot","zu den angeboten","alle anzeigen","image","online-shop","onlineshop","tiefgefroren","gekühlt","original","classic","natur","versch. sorten","100% pflanzlich"}
PACK_ONLY=re.compile(r"^[,;:\-–\s]*(?:je\s+)?\d+(?:[.,]\d+)?\s*[-]?\s*(?:kg|g|l|ml|stück|stk\.?|pckg\.?|btl\.?|fl\.?|becher|dose|flasche)(?:\s*[-,;:].*)?$",re.I)
SET_ONLY=re.compile(r"^\d+er[-\s]*set$",re.I)
ALCOHOL_DESCRIPTOR=re.compile(r"^(?:\d{1,2}(?:[.,]\d+)?\s*[-–]\s*)?\d{1,2}(?:[.,]\d+)?\s*%\s*vol\.?\b.*$",re.I)
PERCENT_DESCRIPTOR=re.compile(r"^\d{1,3}(?:[.,]\d+)?\s*%\s+(?:pflanzlich|fett|frucht|kakao|saft)\b.*$",re.I)
PRICE_SUFFIX=re.compile(r"(?:\s+|^)(?:\d{1,3}[.,]\d{2})\s*(?:€)?\s*(?:App)?\s*$",re.I)
VALIDITY_SUFFIX=re.compile(r"\s+Gültig\s+(?:ab|vom)\s+\d{1,2}\.\d{1,2}\.(?:20)?\d{2}(?:\s+bis\s+(?:zum\s+)?\d{1,2}\.\d{1,2}\.(?:20)?\d{2})?\s*",re.I)
PAYBACK_SUFFIX=re.compile(r"\s+\d+\s*Extra\s*[°º]?\s*P\b.*$",re.I)
PAYBACK_TEXT=re.compile(r"\s+Mit\s+PAYBACK\b.*$",re.I)
APP_SUFFIX=re.compile(r"\s+App\s*$",re.I)

def _collapse_exact_repeat(text:str)->str:
    tokens=text.split(); n=len(tokens)
    if n>=2 and n%2==0:
        half=n//2
        if [t.lower() for t in tokens[:half]]==[t.lower() for t in tokens[half:]]: return " ".join(tokens[:half])
    for half in range(min(6,n//2),0,-1):
        a=[t.lower() for t in tokens[:half]]; b=[t.lower() for t in tokens[half:half*2]]
        if a==b: return " ".join(tokens[:half]+tokens[half*2:])
    return text

def clean_product_name(name:str|None)->str:
    if not name:return ""
    text=re.sub(r"\s+"," ",str(name)).strip().strip(" |•·;:")
    low=text.lower()
    if any(m in low for m in NAVIGATION_MARKERS):
        pos=low.rfind("filiale ")
        if pos>=0: text=text[pos+len("filiale "):].strip()
        else:
            for marker in NAVIGATION_MARKERS:
                pos=text.lower().rfind(marker)
                if pos>=0:text=text[pos+len(marker):].strip()
    text=VALIDITY_SUFFIX.sub(" ",text); text=PAYBACK_SUFFIX.sub("",text); text=PAYBACK_TEXT.sub("",text); text=PRICE_SUFFIX.sub("",text); text=APP_SUFFIX.sub("",text)
    text=re.sub(r"\s+"," ",text).strip(" ,;:|-–"); text=_collapse_exact_repeat(text); text=normalize_known_product_name(text)
    return re.sub(r"\s+"," ",text).strip(" ,;:|-–")[:180]

def product_name_issue(name:str|None)->str|None:
    text=clean_product_name(name); low=text.lower()
    if not text or len(text)<2:return "Produktname fehlt/zu kurz"
    if low in BAD_EXACT:return "Navigation/Überschrift/Eigenschaft statt Produkt"
    if re.fullmatch(r'\d{1,3}(?:[.,]\d+)?\s*%\s*(?:vol\.?)?', text, re.I):return "Nur Alkohol-/Prozentangabe, kein Produkt"
    if ALCOHOL_DESCRIPTOR.match(text):return "Alkoholangabe statt Produktname"
    if PERCENT_DESCRIPTOR.match(text):return "Prozent-/Eigenschaftsangabe statt Produktname"
    if SET_ONLY.match(text):return "Set-Angabe statt Produktname"
    if PACK_ONLY.match(text):return "Nur Packungsangabe, kein Produktname"
    if text.startswith((",",".",";",":","-","–")):return "Produktname beginnt mit Satz-/Packungsfragment"
    if len(text)>110:return "Produktname ungewöhnlich lang"
    if any(m in low for m in NAVIGATION_MARKERS):return "Navigationsinhalt im Produktnamen"
    if "http://" in low or "https://" in low:return "URL statt Produktname"
    return None

def display_product_name(brand:str|None,name:str)->str:
    name=clean_product_name(name); brand=(brand or "").strip()
    if not brand:return name
    nl=name.lower(); bl=brand.lower()
    if nl==bl or nl.startswith(bl+" ") or bl in nl[:max(len(bl)+8,20)]:return name
    return f"{brand} {name}".strip()

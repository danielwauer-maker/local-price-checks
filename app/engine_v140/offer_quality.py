from __future__ import annotations
from dataclasses import dataclass
import re
from .product_cleaning import clean_product_name, product_name_issue

DESCRIPTIVE_ONLY={'tiefgefroren','gekühlt','gekuhlt','frisch','original','classic','klassik','mild','natur','bio','vegan','vegetarisch','extra','aktion','knaller','versch. sorten','verschiedene sorten','sortiert','gemischt','trocken','gekuehlt','tiefgekühlt','tiefgekuehlt','neu','angebot','angebote'}
SAFE_SINGLE_WORDS={'eis','öl','milch','tee','käse','butter','kaffee','joghurt'}
PERCENT_ONLY=re.compile(r'^\s*\d{1,3}(?:[.,]\d+)?\s*%\s*(?:vol\.?|fett\s*i\.?\s*tr\.?)?\s*$',re.I)
ATTRIBUTE_ONLY=re.compile(r'^(?:ca\.?\s*)?(?:tiefgefroren|gekühlt|frisch|original|classic|mild|natur|bio|vegan|vegetarisch|sortiert|gemischt)(?:\s+(?:mild|natur|classic|original|sortiert|gemischt))?$',re.I)

@dataclass(frozen=True)
class OfferQuality:
    accepted: bool
    score: float
    reasons: tuple[str,...]

def _word_tokens(name:str): return re.findall(r"[A-Za-zÄÖÜäöüß0-9][A-Za-zÄÖÜäöüß0-9'’+\-]{1,}",name)

def evaluate_offer(row)->OfferQuality:
    name=clean_product_name(getattr(row,'product_name','')); reasons=[]; issue=product_name_issue(name)
    if issue:return OfferQuality(False,0.0,(issue,))
    low=name.lower().strip(' .,:;-')
    if low in DESCRIPTIVE_ONLY or PERCENT_ONLY.match(name) or ATTRIBUTE_ONLY.match(name):return OfferQuality(False,0.0,('Nur Eigenschaft/Beschreibung, kein identifizierbares Produkt',))
    price=getattr(row,'price',None)
    if price is None or price <= 0 or price > 5000:return OfferQuality(False,0.0,('Aktionspreis fehlt oder unplausibel',))
    tokens=_word_tokens(name); alpha=[t for t in tokens if re.search(r'[A-Za-zÄÖÜäöüß]',t)]
    if not alpha:return OfferQuality(False,0.0,('Keine Produktbezeichnung erkennbar',))
    if len(alpha)==1:
        t=alpha[0]
        if low not in SAFE_SINGLE_WORDS and len(t)<5 and '-' not in t and not any(c.isupper() for c in t[1:]):return OfferQuality(False,0.0,('Einzelwort zu unspezifisch',))
    score=0.50; quantity=getattr(row,'quantity',None); unit=(getattr(row,'unit',None) or '').lower(); unit_price=getattr(row,'unit_price',None)
    if quantity is not None and quantity>0 and unit in {'kg','g','l','ml','stück','stk.','becher','dose','flasche','pckg.','btl.','fl.'}:score+=0.22
    elif unit_price is not None and unit_price>0:score+=0.15
    else:reasons.append('Keine belastbare Packungsgröße; nur bei starker Produktidentität akzeptiert')
    score += 0.13 if (len(alpha)>=2 or '-' in name or any(ch.isdigit() for ch in name)) else 0.07
    confidence=float(getattr(row,'confidence',0.0) or 0.0)
    if confidence>=0.9:score+=0.15
    elif confidence>=0.75:score+=0.10
    elif confidence>=0.6:score+=0.05
    if quantity is None and unit_price is None and len(alpha)<2 and confidence<0.9:return OfferQuality(False,min(score,0.69),tuple(reasons+['Ohne Packung/Grundpreis nicht sicher genug']))
    accepted=score>=0.72
    if not accepted:reasons.append(f'Qualitätsscore {score:.0%} unter 72%')
    return OfferQuality(accepted,min(score,1.0),tuple(reasons))

from __future__ import annotations
import re
from datetime import date
from .week_utils import parse_any_date

ALDI_WEEK=re.compile(r'Wochenangebote\s+Mo\.,?\s*(\d{1,2}\.\d{1,2}\.?)\s*[–-]\s*Sa\.,?\s*(\d{1,2}\.\d{1,2}\.?)',re.I)
ALDI_DATE_FULL=re.compile(r'Wochenangebote\s+Mo\.,?\s*(\d{1,2}\.\d{1,2}\.20\d{2})\s*[–-]\s*Sa\.,?\s*(\d{1,2}\.\d{1,2}\.20\d{2})',re.I)

def aldi_week_range(text:str,ref:date|None=None):
    ref=ref or date.today()
    m=ALDI_DATE_FULL.search(text)
    if m: return parse_any_date(m.group(1),ref),parse_any_date(m.group(2),ref)
    m=ALDI_WEEK.search(text)
    if not m:return None,None
    a=parse_any_date(m.group(1),ref); b=parse_any_date(m.group(2),ref)
    if a and b and b<a: b=b.replace(year=a.year+1)
    return a,b

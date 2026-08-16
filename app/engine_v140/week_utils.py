from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta, datetime
import re

GERMAN_WEEKDAYS = {
    "montag":0,"dienstag":1,"mittwoch":2,"donnerstag":3,
    "freitag":4,"samstag":5,"sonntag":6
}

@dataclass(frozen=True)
class OfferWeek:
    start: date
    end: date

    @property
    def iso_year(self): return self.start.isocalendar().year
    @property
    def iso_week(self): return self.start.isocalendar().week
    @property
    def label(self): return f"KW {self.iso_week} · {self.start:%d.%m.}–{self.end:%d.%m.%Y}"

def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())

def current_offer_week(ref: date | None=None) -> OfferWeek:
    ref = ref or date.today()
    start = monday_of(ref)
    return OfferWeek(start, start + timedelta(days=5))

def next_offer_week(ref: date | None=None) -> OfferWeek:
    ref = ref or date.today()
    start = monday_of(ref) + timedelta(days=7)
    return OfferWeek(start, start + timedelta(days=5))

def week_from_date(d: date) -> OfferWeek:
    start=monday_of(d)
    return OfferWeek(start,start+timedelta(days=5))

def classify_week(valid_from: date, ref: date | None=None) -> str:
    ref=ref or date.today()
    cur=current_offer_week(ref)
    nxt=next_offer_week(ref)
    if cur.start <= valid_from <= cur.end+timedelta(days=1): return "current"
    if nxt.start <= valid_from <= nxt.end+timedelta(days=1): return "next"
    if valid_from > nxt.end: return "future"
    return "past"

def _year4(y: str, ref: date) -> int:
    n=int(y)
    if n < 100: return 2000+n
    return n

def parse_any_date(s: str, ref: date | None=None) -> date | None:
    ref=ref or date.today()
    s=s.strip()
    for fmt in ("%d.%m.%Y","%d.%m.%y","%Y-%m-%d"):
        try: return datetime.strptime(s,fmt).date()
        except ValueError: pass
    m=re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.",s)
    if m:
        d=date(ref.year,int(m.group(2)),int(m.group(1)))
        if (d-ref).days < -180: d=d.replace(year=ref.year+1)
        elif (d-ref).days > 180: d=d.replace(year=ref.year-1)
        return d
    return None

DATE_RANGE_PATTERNS = [
    re.compile(r"gültig\s+vom\s+(\d{1,2}\.\d{1,2}\.(?:20)?\d{2})\s+bis(?:\s+zum)?\s+(\d{1,2}\.\d{1,2}\.(?:20)?\d{2})",re.I),
    re.compile(r"(\d{1,2}\.\d{1,2}\.(?:20)?\d{2})\s*[–-]\s*(\d{1,2}\.\d{1,2}\.(?:20)?\d{2})",re.I),
]
NETTO_RANGE = re.compile(r"gültig\s+von\s+\w+,?\s*(\d{1,2}\.\d{1,2}\.(?:20)?\d{2})\s*[-–]\s*\w+,?\s*(\d{1,2}\.\d{1,2}\.(?:20)?\d{2})",re.I)
AB_MONTAG = re.compile(r"ab\s+montag,?\s*(\d{1,2}\.\d{1,2}\.(?:20)?\d{2})",re.I)
SHORT_RANGE = re.compile(r'(\d{1,2}\.\d{1,2}\.?)\s*[–-]\s*(\d{1,2}\.\d{1,2}\.?)',re.I)
THIS_WEEK_UNTIL = re.compile(r"gültig\s+diese\s+woche\s+bis\s+samstag,?\s*(\d{1,2}\.\d{1,2}\.(?:20)?\d{2})",re.I)
THIS_WEEK_RANGE = re.compile(r"diese\s+woche\s+(\d{1,2}\.\d{1,2}\.?)\s*(?:bis|[–-])\s*(\d{1,2}\.\d{1,2}\.?)",re.I)
WEEK_OFFERS_RANGE = re.compile(r"wochenangebote\s+mo\.?,?\s*(\d{1,2}\.\d{1,2}\.?)\s*[–-]\s*sa\.?,?\s*(\d{1,2}\.\d{1,2}\.?)",re.I)
KW_RE = re.compile(r"\bKW\s*(\d{1,2})\b",re.I)

def infer_validity(text: str, ref: date | None=None):
    """Return (valid_from, valid_to, source, confidence).
    Never silently labels an undated page as next week.
    """
    ref=ref or date.today()
    m=THIS_WEEK_UNTIL.search(text)
    if m:
        b=parse_any_date(m.group(1),ref)
        if b:
            a=monday_of(b)
            return a,b,"this_week_until",0.99

    m=THIS_WEEK_RANGE.search(text)
    if m:
        a=parse_any_date(m.group(1),ref); b=parse_any_date(m.group(2),ref)
        if a and b:
            if b<a: b=b.replace(year=a.year+1)
            if b.weekday()==6: b=b-timedelta(days=1)
            return a,b,"this_week_range",0.97

    m=WEEK_OFFERS_RANGE.search(text)
    if m:
        a=parse_any_date(m.group(1),ref); b=parse_any_date(m.group(2),ref)
        if a and b:
            if b<a: b=b.replace(year=a.year+1)
            return a,b,"week_offers_range",0.98

    m=NETTO_RANGE.search(text)
    if m:
        a=parse_any_date(m.group(1),ref); b=parse_any_date(m.group(2),ref)
        if a and b: return a,b,"explicit_range",1.0

    for pat in DATE_RANGE_PATTERNS:
        m=pat.search(text)
        if m:
            a=parse_any_date(m.group(1),ref); b=parse_any_date(m.group(2),ref)
            if a and b: return a,b,"explicit_range",1.0

    m=SHORT_RANGE.search(text)
    if m:
        a=parse_any_date(m.group(1),ref); b=parse_any_date(m.group(2),ref)
        if a and b:
            if b<a: b=b.replace(year=a.year+1)
            return a,b,'short_range',0.92

    m=AB_MONTAG.search(text)
    if m:
        a=parse_any_date(m.group(1),ref)
        if a: return a,a+timedelta(days=5),"ab_montag",0.95

    m=KW_RE.search(text)
    if m:
        kw=int(m.group(1))
        candidates=[]
        for y in (ref.year-1,ref.year,ref.year+1):
            try:
                d=date.fromisocalendar(y,kw,1)
                candidates.append(d)
            except ValueError: pass
        if candidates:
            a=min(candidates,key=lambda d:abs((d-ref).days))
            return a,a+timedelta(days=5),"calendar_week",0.9

    return None,None,"unknown",0.0

def overlap(a_start: date,a_end: date,b_start: date,b_end: date) -> bool:
    return a_start <= b_end and b_start <= a_end

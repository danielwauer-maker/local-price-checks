from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetailerCapability:
    retailer: str
    scrape_status: str
    rollout_enabled: bool
    note: str


_CAPABILITIES = (
    RetailerCapability(
        "REWE",
        "ready",
        True,
        "Marktbezogener Web-Collector produktiv erprobt.",
    ),
    RetailerCapability(
        "EDEKA",
        "ready",
        True,
        "Zentrale Marktseite plus optionale lokale Händlerquelle; vollständige Zentralquelle ist Pflicht.",
    ),
    RetailerCapability("Lidl", "waiting", False, "Scraping/Qualität noch nicht für Rollout freigegeben."),
    RetailerCapability("ALDI SÜD", "waiting", False, "Scraping/Qualität noch nicht für Rollout freigegeben."),
    RetailerCapability("Netto Marken-Discount", "waiting", False, "Scraping/Qualität noch nicht für Rollout freigegeben."),
    RetailerCapability("PENNY", "waiting", False, "Scraping/Qualität noch nicht für Rollout freigegeben."),
    RetailerCapability("NORMA", "waiting", False, "Scraping/Qualität noch nicht für Rollout freigegeben."),
)


def retailer_capabilities() -> tuple[RetailerCapability, ...]:
    return _CAPABILITIES


def rollout_enabled(retailer: str) -> bool:
    return any(row.retailer == retailer and row.rollout_enabled for row in _CAPABILITIES)

import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { MapPin, Settings } from "lucide-react";
import { useActiveMarketIds, useStore } from "@/lib/app-store";
import { currentOffers, formatEuro } from "@/data/demo";
import { groupIdenticalOffers, marketSummary } from "@/lib/offer-groups";
import { CoverageMapPanel } from "@/components/CoverageMapPanel";
import type { CoverageRegion } from "@/components/CoverageMap";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "LocalPrices – Supermärkte vergleichen & clever sparen" },
      { name: "description", content: "Vergleiche Supermärkte in deinem Umkreis, finde die besten Angebote und erhalte automatisch die optimale Einkaufsliste mit maximaler Ersparnis." },
    ],
  }),
  component: Index,
});

function Index() {
  const { location, productFavorites, profile } = useStore();
  const activeIds = useActiveMarketIds();
  const [regions, setRegions] = useState<CoverageRegion[]>([]);

  useEffect(() => {
    let live = true;
    fetch("/api/coverage")
      .then((response) => response.ok ? response.json() : [])
      .then((payload) => live && setRegions(payload as CoverageRegion[]))
      .catch(() => live && setRegions([]));
    return () => { live = false; };
  }, []);

  const favoriteOffers = useMemo(() => {
    const raw = currentOffers(activeIds).filter((o) => productFavorites.includes(o.product.id));
    return groupIdenticalOffers(raw);
  }, [activeIds, productFavorites]);
  const topOffers = favoriteOffers.slice(0, 4);
  const favoriteHeadline = favoriteOffers.length === 1
    ? "1 Favorit ist aktuell besonders günstig"
    : `${favoriteOffers.length} Favoriten sind aktuell besonders günstig`;

  const coverage = useMemo(() => {
    const distanceKm = (a: { lat: number; lng: number }, b: { lat: number; lng: number }) => {
      const R = 6371;
      const dLat = (b.lat - a.lat) * Math.PI / 180;
      const dLng = (b.lng - a.lng) * Math.PI / 180;
      const p1 = a.lat * Math.PI / 180;
      const p2 = b.lat * Math.PI / 180;
      const h = Math.sin(dLat / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dLng / 2) ** 2;
      return 2 * R * Math.asin(Math.sqrt(h));
    };
    return regions.find((region) => region.status === "live" && distanceKm(location, { lat: region.lat, lng: region.lng }) <= region.radiusKm)
      ?? regions.find((region) => region.status === "building" && distanceKm(location, { lat: region.lat, lng: region.lng }) <= region.radiusKm)
      ?? null;
  }, [regions, location]);

  return (
    <div>
      <section className="gradient-hero relative rounded-b-[2rem] px-5 pb-7 pt-[max(1.5rem,env(safe-area-inset-top))] text-primary-foreground">
        <Link to="/settings" className="absolute right-5 top-[max(1.25rem,env(safe-area-inset-top))] flex h-10 w-10 items-center justify-center rounded-full bg-white/15 transition-colors hover:bg-white/20" aria-label="Einstellungen"><Settings className="h-5 w-5" /></Link>
        <div className="pr-14"><p className="text-xs font-medium uppercase tracking-[0.18em] opacity-75">LocalPrices</p><h1 className="mt-1 text-2xl font-semibold">{profile.displayName ? `Hallo, ${profile.displayName}` : "Clever einkaufen"}</h1><Link to="/settings" className="mt-1 flex items-center gap-1 text-sm opacity-85 hover:opacity-100"><MapPin className="h-3.5 w-3.5" /> {location.label}</Link></div>
      </section>

      <section className="px-5 pt-6">
        <div className="flex items-baseline justify-between"><h2 className="text-base font-semibold">Wo LocalPrices verfügbar ist</h2><span className="text-xs text-muted-foreground">Abdeckung</span></div>
        <div className="mt-3 overflow-hidden rounded-3xl shadow-card"><div className="h-[220px]"><CoverageMapPanel regions={regions.filter((region) => region.status !== "paused")} center={location} /></div></div>
        <div className="surface-card mt-3 p-4">
          {coverage?.status === "live" ? <><p className="text-sm font-semibold text-primary">Deine Region ist freigegeben</p><p className="mt-1 text-xs text-muted-foreground">{coverage.name} · {coverage.verifiedStores} geprüfte Märkte · {coverage.currentOffers} aktuelle Angebotszeilen</p></> : coverage?.status === "building" ? <><p className="text-sm font-semibold">Deine Region wird gerade aufgebaut</p><p className="mt-1 text-xs text-muted-foreground">Märkte und Prospekte werden gesammelt und geprüft. Erst nach QA erscheinen Angebote im Vergleich.</p></> : <><p className="text-sm font-semibold">Für deinen Standort ist noch keine Region freigegeben</p><p className="mt-1 text-xs text-muted-foreground">Grüne Bereiche sind verfügbar, gelbe Bereiche befinden sich im Aufbau.</p></>}
        </div>
      </section>

      <section className="px-5 pt-6">
        <div className="flex items-baseline justify-between"><h2 className="text-base font-semibold">{favoriteHeadline}</h2><Link to="/favoriten" className="text-xs font-semibold text-primary">Favoriten</Link></div>
        <div className="mt-3 space-y-3">
          {topOffers.map((o) => <article key={o.key} className="surface-card flex items-center gap-3 p-3"><span className="flex h-12 w-12 items-center justify-center overflow-hidden rounded-2xl bg-surface-2 text-2xl">{(o.product as any).imageUrl ? <img src={(o.product as any).imageUrl} alt={o.product.name} className="h-full w-full object-cover" /> : o.product.emoji}</span><div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold">{o.product.name}</p><p className="truncate text-[11px] text-muted-foreground">{marketSummary(o.markets)} · bis {o.price.offer!.until}</p></div><div className="text-right"><p className="tabular text-base font-bold text-deal">{formatEuro(o.price.offer!.price)}</p></div></article>)}
          {productFavorites.length === 0 && <p className="surface-card p-5 text-center text-sm text-muted-foreground">Markiere Lieblingsartikel als Favoriten – dann erscheinen ihre Angebote hier.</p>}
          {productFavorites.length > 0 && activeIds.length > 0 && favoriteOffers.length === 0 && <p className="surface-card p-5 text-center text-sm text-muted-foreground">Für deine Favoriten gibt es aktuell keine Angebote in den freigegebenen ausgewählten Märkten.</p>}
        </div>
      </section>
    </div>
  );
}

import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { Crosshair, Heart, MapPin, RefreshCw } from "lucide-react";
import { PageHeader } from "@/components/AppShell";
import { MapPanel } from "@/components/MapPanel";
import { useActiveMarketIds, useStore } from "@/lib/app-store";
import { DEFAULT_LOCATION } from "@/data/demo";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

export const Route = createFileRoute("/maerkte")({
  head: () => ({ meta: [{ title: "Märkte in deiner Nähe – LocalPrices" }] }),
  component: MarketsPage,
});

function MarketsPage() {
  const { location, setLocation, radius, setRadius, marketsInRadius, favoriteMarketsOutsideRadius, refreshingMarketIds, selected, toggleSelected } = useStore();
  const activeIds = useActiveMarketIds();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);
  const navigate = useNavigate();

  function locate() {
    if (!("geolocation" in navigator)) {
      toast.error("Standort wird von diesem Gerät nicht unterstützt.");
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocation({ lat: pos.coords.latitude, lng: pos.coords.longitude, label: "Mein Standort" });
        setLocating(false);
        toast.success("Standort aktualisiert");
      },
      () => {
        setLocating(false);
        setLocation(DEFAULT_LOCATION);
        toast.error("Standort nicht verfügbar – Referenzort aktiv.");
      },
      { enableHighAccuracy: true, timeout: 8000 },
    );
  }

  return (
    <div>
      <PageHeader title="Märkte" subtitle={<Link to="/settings" className="inline-flex items-center gap-1 hover:text-primary"><MapPin className="h-3.5 w-3.5" />{location.label} · {radius} km Umkreis</Link>} />

      <div className="relative mx-5 h-[300px] overflow-hidden rounded-3xl shadow-float">
        <MapPanel center={location} radiusKm={radius} markets={marketsInRadius} selected={selected} onSelect={(id) => setActiveId(id)} activeId={activeId} />
        <button onClick={locate} className="absolute right-3 top-3 z-[500] flex h-11 w-11 items-center justify-center rounded-full bg-surface shadow-float" aria-label="Meinen Standort verwenden"><Crosshair className={cn("h-5 w-5 text-primary", locating && "animate-spin")} strokeWidth={2.2} /></button>
      </div>

      <div className="px-5 pt-5"><div className="flex items-center justify-between text-sm font-medium"><span>Suchradius</span><span className="tabular text-primary">{radius} km</span></div><input type="range" min={2} max={25} step={1} value={radius} onChange={(e) => setRadius(Number(e.target.value))} className="mt-2 h-1.5 w-full cursor-pointer appearance-none rounded-full bg-secondary accent-primary" /></div>

      <section className="mt-5 space-y-3 px-5">
        <div className="flex items-baseline justify-between"><h2 className="text-base font-semibold">{marketsInRadius.length} Märkte gefunden</h2><span className="text-xs text-muted-foreground">{activeIds.length} im Vergleich</span></div>

        {marketsInRadius.map((m) => {
          const chosen = selected.includes(m.id);
          const refreshing = refreshingMarketIds.includes(m.id);
          const released = (m as any).verified !== false;
          return (
            <article key={m.id} onClick={() => navigate({ to: "/markt/$id", params: { id: m.id } })} className={cn("surface-card flex cursor-pointer items-center gap-3 p-4 transition-all", activeId === m.id && "ring-2 ring-primary/40")}>
              <div className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-2xl bg-surface-2 text-[10px] font-bold uppercase text-primary">{(m as any).logoUrl ? <img src={(m as any).logoUrl} alt={m.chain} className="h-full w-full object-contain p-1" /> : m.chain.slice(0, 4)}</div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{m.name}</p>
                <p className="truncate text-xs text-muted-foreground">{m.street}, {m.city} · {m.distance} km</p>
                <p className={cn("mt-1 text-[11px]", refreshing ? "text-primary" : released ? "text-muted-foreground" : "font-medium text-amber-700")}>{refreshing ? (released ? "Angebote werden aktualisiert …" : "Marktdaten werden für QA gesammelt …") : released ? "Antippen für Markt & Prospekt" : "Markt gespeichert · Angebote noch in Prüfung"}</p>
              </div>
              <button onClick={(e) => { e.stopPropagation(); toggleSelected(m.id); }} aria-label={chosen ? "Aus Favoriten entfernen" : "Als Markt-Favorit speichern"} className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-full transition-colors", chosen ? "bg-deal/12 text-deal" : "bg-secondary text-muted-foreground")}>{refreshing ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Heart className={cn("h-5 w-5", chosen && "fill-current")} />}</button>
            </article>
          );
        })}

        {marketsInRadius.length === 0 && <p className="surface-card p-5 text-center text-sm text-muted-foreground">Keine Märkte im Umkreis. Erhöhe den Radius.</p>}
      </section>

      {favoriteMarketsOutsideRadius.length > 0 && <section className="mt-7 space-y-3 px-5 pb-4"><div><h2 className="text-base font-semibold">Weitere Favoriten</h2><p className="text-xs text-muted-foreground">Diese Märkte bleiben gespeichert, werden aktuell aber nicht für Angebote oder den Sparplan verwendet.</p></div>{favoriteMarketsOutsideRadius.map((m) => <article key={m.id} onClick={() => navigate({ to: "/markt/$id", params: { id: m.id } })} className="surface-card flex cursor-pointer items-center gap-3 p-4 opacity-75"><div className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-2xl bg-surface-2 text-[10px] font-bold uppercase text-primary">{(m as any).logoUrl ? <img src={(m as any).logoUrl} alt={m.chain} className="h-full w-full object-contain p-1" /> : m.chain.slice(0, 4)}</div><div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold">{m.name}</p><p className="truncate text-xs text-muted-foreground">{m.street}, {m.city} · {m.distance} km</p><p className="mt-1 text-[11px] font-medium text-muted-foreground">Markt aktuell nicht im Suchgebiet</p></div><button onClick={(e) => { e.stopPropagation(); toggleSelected(m.id); }} aria-label="Favorit entfernen" className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-deal/12 text-deal"><Heart className="h-5 w-5 fill-current" /></button></article>)}</section>}
    </div>
  );
}

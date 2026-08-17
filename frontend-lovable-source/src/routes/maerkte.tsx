import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { Crosshair, Heart, MapPin } from "lucide-react";
import { PageHeader } from "@/components/AppShell";
import { MapPanel } from "@/components/MapPanel";
import { useStore } from "@/lib/app-store";
import { DEFAULT_LOCATION } from "@/data/demo";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

export const Route = createFileRoute("/maerkte")({
  head: () => ({ meta: [{ title: "Märkte in deiner Nähe – LocalPrices" }] }),
  component: MarketsPage,
});

function MarketsPage() {
  const { location, setLocation, radius, setRadius, marketsInRadius, selected, toggleSelected } = useStore();
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
        <button onClick={locate} className="absolute right-3 top-3 z-[500] flex h-11 w-11 items-center justify-center rounded-full bg-surface shadow-float" aria-label="Meinen Standort verwenden">
          <Crosshair className={cn("h-5 w-5 text-primary", locating && "animate-spin")} strokeWidth={2.2} />
        </button>
      </div>

      <div className="px-5 pt-5">
        <div className="flex items-center justify-between text-sm font-medium"><span>Suchradius</span><span className="tabular text-primary">{radius} km</span></div>
        <input type="range" min={2} max={25} step={1} value={radius} onChange={(e) => setRadius(Number(e.target.value))} className="mt-2 h-1.5 w-full cursor-pointer appearance-none rounded-full bg-secondary accent-primary" />
      </div>

      <section className="mt-5 space-y-3 px-5">
        <div className="flex items-baseline justify-between"><h2 className="text-base font-semibold">{marketsInRadius.length} Märkte gefunden</h2><span className="text-xs text-muted-foreground">{selected.length} im Vergleich</span></div>

        {marketsInRadius.map((m) => {
          const chosen = selected.includes(m.id);
          return (
            <article key={m.id} onClick={() => navigate({ to: "/markt/$id", params: { id: m.id } })} className={cn("surface-card flex cursor-pointer items-center gap-3 p-4 transition-all", activeId === m.id && "ring-2 ring-primary/40")}>
              <div className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-2xl bg-surface-2 text-[10px] font-bold uppercase text-primary">
                {(m as any).logoUrl ? <img src={(m as any).logoUrl} alt={m.chain} className="h-full w-full object-contain p-1" /> : m.chain.slice(0, 4)}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{m.name}</p>
                <p className="truncate text-xs text-muted-foreground">{m.street}, {m.city} · {m.distance} km</p>
                <p className="mt-1 text-[11px] text-muted-foreground">Antippen für Markt & Prospekt</p>
              </div>
              <button onClick={(e) => { e.stopPropagation(); toggleSelected(m.id); }} aria-label={chosen ? "Aus Vergleich entfernen" : "Zum Vergleich hinzufügen"} className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-full transition-colors", chosen ? "bg-deal/12 text-deal" : "bg-secondary text-muted-foreground")}>
                <Heart className={cn("h-5 w-5", chosen && "fill-current")} />
              </button>
            </article>
          );
        })}

        {marketsInRadius.length === 0 && <p className="surface-card p-5 text-center text-sm text-muted-foreground">Keine Märkte im Umkreis. Erhöhe den Radius.</p>}
      </section>
    </div>
  );
}

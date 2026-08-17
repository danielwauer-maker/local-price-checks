import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Check, Crosshair, Heart, Star } from "lucide-react";
import { PageHeader } from "@/components/AppShell";
import { MapPanel } from "@/components/MapPanel";
import { useStore } from "@/lib/app-store";
import { DEFAULT_LOCATION } from "@/data/demo";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

export const Route = createFileRoute("/maerkte")({
  head: () => ({
    meta: [
      { title: "Märkte in deiner Nähe – LocalPrices" },
      {
        name: "description",
        content:
          "Finde Supermärkte im Umkreis deines Standorts auf der Karte, wähle deine Vergleichsmärkte und setze Favoriten.",
      },
      { property: "og:title", content: "Märkte in deiner Nähe – LocalPrices" },
      {
        property: "og:description",
        content: "Karte mit Umkreissuche: Märkte auswählen und Preise vergleichen.",
      },
    ],
  }),
  component: MarketsPage,
});

function MarketsPage() {
  const {
    location,
    setLocation,
    radius,
    setRadius,
    marketsInRadius,
    selected,
    toggleSelected,
    favorites,
    toggleFavorite,
  } = useStore();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);

  function locate() {
    if (!("geolocation" in navigator)) {
      toast.error("Standort wird von diesem Gerät nicht unterstützt.");
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocation({
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          label: "Mein Standort",
        });
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
      <PageHeader title="Märkte" subtitle={`${location.label} · ${radius} km Umkreis`} />

      <div className="relative mx-5 h-[300px] overflow-hidden rounded-3xl shadow-float">
        <MapPanel
          center={location}
          radiusKm={radius}
          markets={marketsInRadius}
          selected={selected}
          onSelect={(id) => setActiveId(id)}
          activeId={activeId}
        />
        <button
          onClick={locate}
          className="absolute right-3 top-3 z-[500] flex h-11 w-11 items-center justify-center rounded-full bg-surface shadow-float"
          aria-label="Meinen Standort verwenden"
        >
          <Crosshair
            className={cn("h-5 w-5 text-primary", locating && "animate-spin")}
            strokeWidth={2.2}
          />
        </button>
      </div>

      <div className="px-5 pt-5">
        <div className="flex items-center justify-between text-sm font-medium">
          <span>Suchradius</span>
          <span className="tabular text-primary">{radius} km</span>
        </div>
        <input
          type="range"
          min={2}
          max={25}
          step={1}
          value={radius}
          onChange={(e) => setRadius(Number(e.target.value))}
          className="mt-2 h-1.5 w-full cursor-pointer appearance-none rounded-full bg-secondary accent-primary"
        />
      </div>

      <section className="mt-5 space-y-3 px-5">
        <div className="flex items-baseline justify-between">
          <h2 className="text-base font-semibold">{marketsInRadius.length} Märkte gefunden</h2>
          <span className="text-xs text-muted-foreground">{selected.length} im Vergleich</span>
        </div>

        {marketsInRadius.map((m) => {
          const chosen = selected.includes(m.id);
          return (
            <article
              key={m.id}
              onClick={() => setActiveId(m.id)}
              className={cn(
                "surface-card flex items-center gap-3 p-4 transition-all",
                activeId === m.id && "ring-2 ring-primary/40",
              )}
            >
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-primary-soft text-[10px] font-bold uppercase text-primary">
                {m.chain.slice(0, 4)}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{m.name}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {m.street}, {m.city} · {m.distance} km
                </p>
                <p className="mt-1 flex items-center gap-2 text-[11px] text-muted-foreground">
                  <span className="flex items-center gap-0.5">
                    <Star className="h-3 w-3 fill-accent text-accent" /> {m.rating.toFixed(1)}
                  </span>
                  <span>bis {m.openUntil} Uhr</span>
                </p>
              </div>
              <div className="flex flex-col items-center gap-2">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    toggleFavorite(m.id);
                  }}
                  aria-label="Favorit"
                >
                  <Heart
                    className={cn(
                      "h-5 w-5",
                      favorites.includes(m.id)
                        ? "fill-deal text-deal"
                        : "text-muted-foreground",
                    )}
                  />
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    toggleSelected(m.id);
                  }}
                  className={cn(
                    "flex h-7 items-center gap-1 rounded-full px-3 text-[11px] font-semibold transition-colors",
                    chosen
                      ? "bg-primary text-primary-foreground"
                      : "bg-secondary text-secondary-foreground",
                  )}
                >
                  {chosen && <Check className="h-3 w-3" />}
                  {chosen ? "aktiv" : "wählen"}
                </button>
              </div>
            </article>
          );
        })}

        {marketsInRadius.length === 0 && (
          <p className="surface-card p-5 text-center text-sm text-muted-foreground">
            Keine Märkte im Umkreis. Erhöhe den Radius.
          </p>
        )}
      </section>
    </div>
  );
}

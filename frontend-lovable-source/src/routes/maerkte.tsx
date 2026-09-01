import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { ChevronDown, MapPin, Navigation, Save, Store } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/AppShell";
import { FilterChips } from "@/components/lokero/FilterChips";
import { MarketCard } from "@/components/lokero/MarketCard";
import { EmptyState, ErrorState, SkeletonList } from "@/components/lokero/States";
import MapPanel from "@/components/MapPanel";
import { useStore } from "@/lib/app-store";
import { cn } from "@/lib/utils";
import { fetchMarkets, persistLocation, type Market } from "@/services/lokero-api";
import { fetchAccountState, persistAccountProfile } from "@/services/lokero-account-api";

export const Route = createFileRoute("/maerkte")({
  head: () => ({
    meta: [
      { title: "Märkte in deiner Nähe – Spareno" },
      {
        name: "description",
        content: "Alle Supermärkte in deinem Umkreis auf der Karte, sortiert nach echter Entfernung.",
      },
      { property: "og:title", content: "Märkte in deiner Nähe – Spareno" },
      {
        property: "og:description",
        content: "Karte mit Standort- und Umkreissuche für deine Märkte.",
      },
    ],
  }),
  component: MarketsScreen,
});

const FILTERS = [
  { id: "alle", label: "Alle" },
  { id: "entfernung", label: "Entfernung", dropdown: true },
];

type PhysicalMarket = Market & { physicalMarketIds: string[] };

function normalizeMarketIdentity(value: string) {
  return value
    .trim()
    .toLocaleLowerCase("de")
    .replace(/ß/g, "ss")
    .replace(/[^a-z0-9]+/g, "");
}

function physicalMarketKey(market: Market) {
  return [market.chain, market.city, market.street]
    .map((value) => normalizeMarketIdentity(String(value ?? "")))
    .join("|");
}

export function dedupePhysicalMarkets(markets: Market[], favoriteMarkets: string[]): PhysicalMarket[] {
  const favorites = new Set(favoriteMarkets);
  const grouped = new Map<string, PhysicalMarket>();

  for (const market of markets) {
    const key = physicalMarketKey(market);
    const existing = grouped.get(key);
    if (!existing) {
      grouped.set(key, { ...market, physicalMarketIds: [market.id] });
      continue;
    }

    existing.physicalMarketIds.push(market.id);
    const existingFavorite = favorites.has(existing.id);
    const candidateFavorite = favorites.has(market.id);
    if (!existingFavorite && candidateFavorite) {
      grouped.set(key, { ...market, physicalMarketIds: existing.physicalMarketIds });
    }
  }

  return [...grouped.values()];
}

function haversineKm(
  from: { lat: number; lng: number },
  to: { lat: number; lng: number },
) {
  const rad = (value: number) => (value * Math.PI) / 180;
  const dLat = rad(to.lat - from.lat);
  const dLng = rad(to.lng - from.lng);
  const lat1 = rad(from.lat);
  const lat2 = rad(to.lat);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return 6371.0088 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
}

function MarketsScreen() {
  const {
    location,
    radius,
    setLocation,
    setRadius,
    favoriteMarkets,
    toggleFavoriteMarket,
  } = useStore();
  const [filter, setFilter] = useState("alle");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [locationOpen, setLocationOpen] = useState(false);
  const [postalCode, setPostalCode] = useState("");
  const [city, setCity] = useState("");
  const [savingLocation, setSavingLocation] = useState(false);

  useEffect(() => {
    let active = true;
    void fetchAccountState()
      .then((state) => {
        if (!active || !state.profile) return;
        setPostalCode(state.profile.postalCode || "");
        setCity(state.profile.city || "");
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  const query = useQuery({
    queryKey: ["markets", radius, location.lat, location.lng],
    queryFn: async () => {
      // Persist the latest local position before the backend applies its radius
      // gate. This avoids a stale server position after changing location here.
      await persistLocation({ ...location, radius });
      return fetchMarkets(radius);
    },
  });

  const markets = useMemo(() => {
    const list = dedupePhysicalMarkets(
      (query.data ?? [])
        .map((market) => ({
          ...market,
          distanceKm: haversineKm(location, { lat: market.lat, lng: market.lng }),
        }))
        .filter((market) => market.distanceKm <= radius + 0.01),
      favoriteMarkets,
    );

    if (filter === "entfernung") list.sort((a, b) => a.distanceKm - b.distanceKm);
    return list;
  }, [query.data, favoriteMarkets, filter, location, radius]);

  useEffect(() => {
    // Old imports could expose two Store rows for the same physical branch. If
    // both legacy ids were favorited, keep the visible representative and drop
    // the hidden duplicate ids so offer requests no longer include both rows.
    for (const market of markets) {
      const selectedIds = market.physicalMarketIds.filter((id) => favoriteMarkets.includes(id));
      if (selectedIds.length <= 1) continue;
      for (const id of selectedIds) {
        if (id !== market.id) toggleFavoriteMarket(id);
      }
    }
  }, [markets, favoriteMarkets, toggleFavoriteMarket]);

  async function saveManualLocation() {
    if (!/^\d{5}$/.test(postalCode.trim()) || !city.trim()) {
      toast.error("Bitte eine fünfstellige PLZ und den Ort eingeben");
      return;
    }
    setSavingLocation(true);
    try {
      const state = await persistAccountProfile({
        postalCode: postalCode.trim(),
        city: city.trim(),
        radiusKm: radius,
      });
      const profile = state.profile;
      if (profile?.latitude == null || profile.longitude == null) {
        throw new Error("Für diesen Standort konnten keine Koordinaten ermittelt werden");
      }
      setLocation({
        lat: profile.latitude,
        lng: profile.longitude,
        label: [profile.postalCode, profile.city].filter(Boolean).join(" "),
      });
      setLocationOpen(false);
      toast.success("Standort aktualisiert");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Standort konnte nicht gespeichert werden");
    } finally {
      setSavingLocation(false);
    }
  }

  function useGps() {
    if (!navigator.geolocation) {
      toast.error("GPS ist in diesem Browser nicht verfügbar");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setLocation({
          lat: position.coords.latitude,
          lng: position.coords.longitude,
          label: "Mein Standort",
        });
        setLocationOpen(false);
        toast.success("GPS-Standort übernommen");
      },
      () => toast.error("Standortfreigabe wurde abgelehnt"),
      { enableHighAccuracy: true, timeout: 10_000 },
    );
  }

  return (
    <div>
      <PageHeader title="Märkte" subtitle={`Umkreis ${radius} km · ${location.label}`} />

      <div className="space-y-2 bg-surface px-4 pb-3">
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setLocationOpen((value) => !value)}
            className="flex h-10 min-w-0 flex-1 items-center gap-2 rounded-xl border border-border bg-surface px-3 text-left"
          >
            <MapPin className="h-4 w-4 shrink-0 text-primary" />
            <span className="min-w-0 flex-1 truncate text-[12px] font-semibold text-navy">{location.label}</span>
            <ChevronDown className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform", locationOpen && "rotate-180")} />
          </button>
          <select
            aria-label="Suchradius"
            value={radius}
            onChange={(event) => setRadius(Number(event.target.value))}
            className="h-10 rounded-xl border border-border bg-surface px-3 text-[12px] font-semibold text-navy outline-none focus:border-primary"
          >
            {[5, 10, 15, 20, 25, 30, 40, 50].map((km) => (
              <option key={km} value={km}>{km} km</option>
            ))}
          </select>
        </div>

        {locationOpen && (
          <div className="rounded-2xl border border-border bg-muted-surface/45 p-3">
            <div className="grid grid-cols-[110px_minmax(0,1fr)] gap-2">
              <input
                value={postalCode}
                onChange={(event) => setPostalCode(event.target.value.replace(/\D/g, "").slice(0, 5))}
                inputMode="numeric"
                placeholder="PLZ"
                className="h-10 rounded-xl border border-border bg-surface px-3 text-[13px] outline-none focus:border-primary"
              />
              <input
                value={city}
                onChange={(event) => setCity(event.target.value)}
                placeholder="Ort"
                className="h-10 min-w-0 rounded-xl border border-border bg-surface px-3 text-[13px] outline-none focus:border-primary"
              />
            </div>
            <div className="mt-2 flex gap-2">
              <button
                type="button"
                onClick={() => void saveManualLocation()}
                disabled={savingLocation}
                className="flex h-10 flex-1 items-center justify-center gap-1.5 rounded-xl bg-primary text-[12px] font-semibold text-primary-foreground disabled:opacity-60"
              >
                <Save className="h-4 w-4" /> {savingLocation ? "Speichert …" : "Standort übernehmen"}
              </button>
              <button
                type="button"
                onClick={useGps}
                className="flex h-10 flex-1 items-center justify-center gap-1.5 rounded-xl border border-primary/20 bg-primary-soft text-[12px] font-semibold text-primary"
              >
                <Navigation className="h-4 w-4" /> GPS verwenden
              </button>
            </div>
          </div>
        )}

        <FilterChips options={FILTERS} value={filter} onChange={setFilter} />
      </div>

      <div className="px-4 pt-3">
        <div className="relative h-[260px] overflow-hidden rounded-2xl border border-border sm:h-[280px]">
          <MapPanel
            center={location}
            radiusKm={radius}
            markets={markets}
            activeId={activeId}
            onSelect={setActiveId}
          />
          <span className="tabular pointer-events-none absolute right-2 top-2 rounded-full bg-surface/95 px-2 py-1 text-[10px] font-semibold text-navy shadow-raised">
            {radius} km
          </span>
        </div>
      </div>

      <section className="space-y-2.5 px-4 pt-4">
        {query.isLoading && <SkeletonList count={4} />}
        {query.isError && <ErrorState onRetry={() => query.refetch()} />}
        {query.isSuccess && markets.length === 0 && (
          <EmptyState
            icon={Store}
            title="Keine Märkte im Umkreis"
            description="Erhöhe deinen Suchradius oder passe oben deinen Standort an."
          />
        )}
        {markets.map((market, index) => (
          <MarketCard
            key={physicalMarketKey(market)}
            market={market}
            rank={index + 1}
            isFavorite={market.physicalMarketIds.some((id) => favoriteMarkets.includes(id))}
            onToggleFavorite={() => {
              const selectedIds = market.physicalMarketIds.filter((id) => favoriteMarkets.includes(id));
              if (selectedIds.length > 0) {
                selectedIds.forEach((id) => toggleFavoriteMarket(id));
              } else {
                toggleFavoriteMarket(market.id);
              }
            }}
            onSelect={() => setActiveId(market.id)}
          />
        ))}
      </section>
    </div>
  );
}

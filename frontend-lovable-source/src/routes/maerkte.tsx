import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Store } from "lucide-react";
import { PageHeader } from "@/components/AppShell";
import { FilterChips } from "@/components/lokero/FilterChips";
import { MarketCard } from "@/components/lokero/MarketCard";
import { EmptyState, ErrorState, SkeletonList } from "@/components/lokero/States";
import MapPanel from "@/components/MapPanel";
import { useStore } from "@/lib/app-store";
import { fetchMarkets } from "@/services/lokero-api";

export const Route = createFileRoute("/maerkte")({
  head: () => ({
    meta: [
      { title: "Märkte in deiner Nähe – Lokero" },
      {
        name: "description",
        content:
          "Alle Supermärkte in deinem Umkreis auf der Karte, sortiert nach Entfernung, Sparpotenzial und Öffnungszeiten.",
      },
      { property: "og:title", content: "Märkte in deiner Nähe – Lokero" },
      {
        property: "og:description",
        content: "Karte mit Umkreissuche und Sparpotenzial je Markt.",
      },
    ],
  }),
  component: MarketsScreen,
});

const FILTERS = [
  { id: "alle", label: "Alle" },
  { id: "entfernung", label: "Entfernung", dropdown: true },
  { id: "sparpotenzial", label: "Sparpotenzial", dropdown: true },
  { id: "oeffnung", label: "Öffnungszeiten", dropdown: true },
];

function MarketsScreen() {
  const { location, radius, favoriteMarkets, toggleFavoriteMarket } = useStore();
  const [filter, setFilter] = useState("alle");
  const [activeId, setActiveId] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["markets", radius],
    queryFn: () => fetchMarkets(radius),
  });

  const markets = useMemo(() => {
    const list = [...(query.data ?? [])];
    if (filter === "entfernung") list.sort((a, b) => a.distanceKm - b.distanceKm);
    else if (filter === "sparpotenzial") list.sort((a, b) => b.savingPotential - a.savingPotential);
    else if (filter === "oeffnung") list.sort((a, b) => b.openUntil.localeCompare(a.openUntil));
    return list;
  }, [query.data, filter]);

  return (
    <div>
      <PageHeader title="Märkte" subtitle={`Umkreis ${radius} km · ${location.label}`} />

      <div className="bg-surface px-4 pb-3">
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
            description="Erhöhe deinen Suchradius, um mehr Märkte in deiner Nähe zu finden."
          />
        )}
        {markets.map((m, i) => (
          <MarketCard
            key={m.id}
            market={m}
            rank={i + 1}
            isFavorite={favoriteMarkets.includes(m.id)}
            onToggleFavorite={() => toggleFavoriteMarket(m.id)}
            onSelect={() => setActiveId(m.id)}
          />
        ))}
      </section>
    </div>
  );
}

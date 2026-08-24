import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Store } from "lucide-react";
import { TopBar } from "@/components/AppShell";
import { SavingsHero } from "@/components/lokero/SavingsHero";
import { SearchBar } from "@/components/lokero/SearchBar";
import { CategoryGrid } from "@/components/lokero/CategoryGrid";
import { OfferTile } from "@/components/lokero/OfferCard";
import { SkeletonCard } from "@/components/lokero/States";
import { RegionAvailabilityCard } from "@/components/lokero/RegionAvailabilityCard";
import {
  fetchFeatures,
  fetchMarkets,
  fetchRegionStatus,
  fetchTopOffers,
  fetchWeeklySavings,
} from "@/services/lokero-api";
import { OPTIMIZED_TRIP } from "@/data/lokero";
import { useStore } from "@/lib/app-store";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Lokero – Alles in deiner Nähe. Das Beste für dich." },
      {
        name: "description",
        content:
          "Lokero ist dein smarter lokaler Einkaufsassistent: Märkte in der Nähe, aktuelle Angebote und eine automatisch optimierte Einkaufsliste.",
      },
      { property: "og:title", content: "Lokero – Dein Einkauf. Lokal. Clever. Einfach." },
      {
        property: "og:description",
        content: "Märkte vergleichen, Angebote entdecken und den Einkauf automatisch optimieren.",
      },
    ],
  }),
  component: StartScreen,
});

function StartScreen() {
  const { radius, regionStatusOverride } = useStore();
  const features = useQuery({ queryKey: ["lokero-features"], queryFn: fetchFeatures });
  const savings = useQuery({ queryKey: ["weekly-savings"], queryFn: fetchWeeklySavings });
  const offers = useQuery({ queryKey: ["top-offers"], queryFn: () => fetchTopOffers(6) });
  const markets = useQuery({ queryKey: ["markets", radius], queryFn: () => fetchMarkets(radius) });
  const region = useQuery({
    queryKey: ["region-status", regionStatusOverride],
    queryFn: () =>
      fetchRegionStatus(regionStatusOverride === "auto" ? undefined : regionStatusOverride),
  });

  const flags = features.data?.features;
  const showRegion = flags?.region_availability !== false;
  const showSavings = flags?.savings !== false && flags?.optimization !== false && savings.data?.enabled !== false;

  return (
    <div className="pb-4">
      <TopBar />

      <div className="space-y-5 px-4 pt-3">
        {showRegion && (region.data ? (
          <RegionAvailabilityCard region={region.data} markets={markets.data ?? []} radiusKm={radius} />
        ) : (
          <div className="h-[186px] animate-pulse rounded-2xl bg-muted-surface" />
        ))}

        {showSavings && savings.data ? (
          <SavingsHero
            amount={savings.data.amount}
            combinationLabel={savings.data.combinationLabel}
            itemCount={savings.data.itemCount}
            marketCount={savings.data.marketCount}
            distanceKm={savings.data.distanceKm}
            explanation={OPTIMIZED_TRIP.savingsExplanation}
          />
        ) : (
          <section className="rounded-2xl bg-primary-deep p-4 text-white">
            <div className="flex items-start gap-3">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-white/12">
                <Store className="h-5 w-5" />
              </span>
              <div className="min-w-0">
                <p className="text-[12px] font-medium text-white/75">Aktuell in deiner Region</p>
                <h2 className="mt-0.5 text-[20px] font-bold leading-tight">Echte Angebote entdecken</h2>
                <p className="mt-1 text-[12px] leading-relaxed text-white/80">
                  {region.data?.activeMarkets
                    ? `${region.data.activeMarkets} freigegebene ${region.data.activeMarkets === 1 ? "Markt" : "Märkte"} · ${region.data.currentOffers ?? offers.data?.length ?? 0} aktuelle Angebote`
                    : `${offers.data?.length ?? 0} aktuelle Angebote verfügbar`}
                </p>
              </div>
            </div>
            <Link
              to="/angebote"
              className="mt-4 flex h-11 w-full items-center justify-center gap-1.5 rounded-xl bg-white text-[13px] font-semibold text-primary-deep"
            >
              Angebote ansehen <ArrowRight className="h-4 w-4" />
            </Link>
          </section>
        )}

        <SearchBar />
        <CategoryGrid />

        <section>
          <div className="flex items-baseline justify-between">
            <h2 className="text-[15px] font-semibold text-navy">Deine besten Angebote</h2>
            <Link
              to="/angebote"
              className="flex items-center gap-0.5 text-[12px] font-semibold text-primary"
            >
              Alle anzeigen <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>

          <div className="no-scrollbar -mx-4 mt-3 flex gap-2.5 overflow-x-auto px-4 pb-1">
            {offers.isLoading &&
              Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="w-[132px] shrink-0">
                  <SkeletonCard />
                </div>
              ))}
            {offers.data?.map((o) => <OfferTile key={`${o.productId}-${o.marketId}`} offer={o} />)}
          </div>
        </section>
      </div>
    </div>
  );
}

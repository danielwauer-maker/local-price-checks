import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Heart, Store } from "lucide-react";
import { TopBar } from "@/components/AppShell";
import { SavingsHero } from "@/components/lokero/SavingsHero";
import { OfferTile } from "@/components/lokero/OfferCard";
import { SkeletonCard } from "@/components/lokero/States";
import { RegionAvailabilityCard } from "@/components/lokero/RegionAvailabilityCard";
import { fetchFeatures, fetchMarkets, fetchRegionStatus, fetchWeeklySavings } from "@/services/lokero-api";
import { fetchMatchedFavoriteOffers } from "@/services/lokero-personalization-api";
import { OPTIMIZED_TRIP } from "@/data/lokero";
import { useStore } from "@/lib/app-store";

export const Route = createFileRoute("/")({
  head: () => ({ meta: [{ title: "Spareno – Alles in deiner Nähe. Das Beste für dich." }] }),
  component: StartScreen,
});

function StartScreen() {
  const { radius, regionStatusOverride, favoriteMarkets } = useStore();
  const hasFavoriteMarkets = favoriteMarkets.length > 0;
  const favoriteMarketKey = [...favoriteMarkets].sort().join(",");
  const features = useQuery({ queryKey: ["lokero-features"], queryFn: fetchFeatures });
  const savings = useQuery({ queryKey: ["weekly-savings"], queryFn: fetchWeeklySavings });
  const matchedOffers = useQuery({
    queryKey: ["favorite-matched-offers", favoriteMarketKey],
    queryFn: fetchMatchedFavoriteOffers,
    enabled: hasFavoriteMarkets,
  });
  const markets = useQuery({ queryKey: ["markets", radius], queryFn: () => fetchMarkets(radius) });
  const region = useQuery({ queryKey: ["region-status", regionStatusOverride], queryFn: () => fetchRegionStatus(regionStatusOverride === "auto" ? undefined : regionStatusOverride) });

  const flags = features.data?.features;
  const showRegion = flags?.region_availability !== false;
  const showSavings = flags?.savings !== false && flags?.optimization !== false && savings.data?.enabled !== false;
  const prioritizedMatchedOffers = hasFavoriteMarkets
    ? [...(matchedOffers.data ?? [])].sort((a, b) => {
        const aFavorite = favoriteMarkets.includes(a.marketId) ? 1 : 0;
        const bFavorite = favoriteMarkets.includes(b.marketId) ? 1 : 0;
        return bFavorite - aFavorite;
      })
    : [];

  return (
    <div className="pb-4">
      <TopBar />
      <div className="space-y-5 px-4 pt-3">
        {showRegion && !region.data && <div className="h-[82px] animate-pulse rounded-2xl bg-muted-surface" />}
        {showRegion && region.data && region.data.status !== "available" && (
          <RegionAvailabilityCard region={region.data} markets={markets.data ?? []} radiusKm={radius} />
        )}

        {showSavings && savings.data ? (
          <SavingsHero amount={savings.data.amount} combinationLabel={savings.data.combinationLabel} itemCount={savings.data.itemCount} marketCount={savings.data.marketCount} distanceKm={savings.data.distanceKm} explanation={OPTIMIZED_TRIP.savingsExplanation} />
        ) : (
          <section className="rounded-2xl bg-primary-deep p-4 text-white">
            <div className="flex items-start gap-3">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-white/12"><Store className="h-5 w-5" /></span>
              <div className="min-w-0">
                <p className="text-[12px] font-medium text-white/75">Aktuell in deiner Region</p>
                <h2 className="mt-0.5 text-[20px] font-bold leading-tight">{hasFavoriteMarkets ? "Alle Angebote entdecken" : "Deine Märkte auswählen"}</h2>
                <p className="mt-1 text-[12px] leading-relaxed text-white/80">
                  {hasFavoriteMarkets
                    ? (region.data?.activeMarkets ? `${region.data.activeMarkets} freigegebene ${region.data.activeMarkets === 1 ? "Markt" : "Märkte"} · ${region.data.currentOffers ?? 0} aktuelle Angebote` : "Aktuelle lokale Angebote ansehen")
                    : "Wähle die Märkte aus, deren Angebote Spareno für dich anzeigen soll."}
                </p>
              </div>
            </div>
            <Link to={hasFavoriteMarkets ? "/angebote" : "/maerkte"} className="mt-4 flex h-11 w-full items-center justify-center gap-1.5 rounded-xl bg-white text-[13px] font-semibold text-primary-deep">
              {hasFavoriteMarkets ? "Angebote ansehen" : "Märkte auswählen"} <ArrowRight className="h-4 w-4" />
            </Link>
          </section>
        )}

        <section>
          <div className="flex items-baseline justify-between gap-3">
            <h2 className="text-[15px] font-semibold text-navy">Passende Angebote zu deinen Favoriten</h2>
            <Link to="/favoriten" className="shrink-0 text-[12px] font-semibold text-primary">Favoriten</Link>
          </div>

          {!hasFavoriteMarkets && (
            <div className="mt-2 rounded-xl border border-border bg-surface px-3 py-3">
              <p className="text-[12px] font-semibold text-navy">Noch keine Märkte ausgewählt</p>
              <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">Wähle mindestens einen Markt aus. Danach zeigt Spareno passende Angebote aus deiner persönlichen Marktauswahl.</p>
              <Link to="/maerkte" className="mt-3 inline-flex h-9 items-center rounded-xl bg-primary px-3 text-[11px] font-semibold text-primary-foreground">Märkte auswählen</Link>
            </div>
          )}

          {hasFavoriteMarkets && matchedOffers.isLoading && <div className="mt-3 grid grid-cols-2 gap-2.5 sm:grid-cols-3">{Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)}</div>}
          {hasFavoriteMarkets && !matchedOffers.isLoading && prioritizedMatchedOffers.length === 0 && (
            <div className="mt-3 rounded-2xl border border-border bg-surface p-4 text-center">
              <Heart className="mx-auto h-5 w-5 text-discount" />
              <p className="mt-2 text-[12px] font-semibold text-navy">Noch keine passenden Angebote</p>
              <p className="mt-1 text-[11px] text-muted-foreground">Merke dir Produkte oder Produktfamilien wie Bier, Cola oder Fisch.</p>
            </div>
          )}
          {hasFavoriteMarkets && prioritizedMatchedOffers.length > 0 && <div className="mt-3 grid grid-cols-2 gap-2.5 sm:grid-cols-3">{prioritizedMatchedOffers.map((offer) => <OfferTile key={`${offer.productId}-${offer.marketId}`} offer={offer} />)}</div>}
        </section>
      </div>
    </div>
  );
}

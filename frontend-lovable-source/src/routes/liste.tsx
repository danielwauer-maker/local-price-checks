import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ArrowRight, Clock3, ListChecks, Minus, Plus, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/AppShell";
import { Tabs } from "@/components/lokero/FilterChips";
import {
  OptimizedTripSummary,
  ShoppingMarketGroup,
  TripRouteRow,
} from "@/components/lokero/OptimizedTrip";
import { ProductThumb } from "@/components/lokero/CategoryIcon";
import { MarketLogo } from "@/components/lokero/MarketLogo";
import { EmptyState, ErrorState, SkeletonList } from "@/components/lokero/States";
import { useStore } from "@/lib/app-store";
import {
  bestPriceFor,
  fetchFeatures,
  fetchOptimizedTrip,
  getMarket,
  getProduct,
} from "@/services/lokero-api";
import { formatEuro } from "@/lib/format";

export const Route = createFileRoute("/liste")({
  head: () => ({
    meta: [
      { title: "Optimierte Einkaufsliste – Lokero" },
      {
        name: "description",
        content:
          "Deine Einkaufsliste, automatisch auf die günstigste Marktkombination optimiert – inklusive Fahrtkosten, Stopps und Ersparnis.",
      },
      { property: "og:title", content: "Optimierte Einkaufsliste – Lokero" },
      {
        property: "og:description",
        content: "Optimale Marktkombination, Fahrtkosten und Ersparnis auf einen Blick.",
      },
    ],
  }),
  component: ListScreen,
});

const TABS = [
  { id: "meine", label: "Meine Liste" },
  { id: "optimiert", label: "Optimiert" },
];

function ListScreen() {
  const [tab, setTab] = useState("optimiert");
  const { listEntries, setQty, addToList, clearList } = useStore();
  const features = useQuery({ queryKey: ["lokero-features"], queryFn: fetchFeatures });
  const trip = useQuery({ queryKey: ["optimized-trip"], queryFn: fetchOptimizedTrip });
  const optimizationEnabled = features.data?.features.optimization !== false && trip.data?.enabled !== false;

  return (
    <div>
      <PageHeader
        title="Liste"
        action={
          listEntries.length > 0 ? (
            <button
              onClick={() => {
                clearList();
                toast.success("Liste geleert");
              }}
              className="tap-target grid place-items-center rounded-xl text-muted-foreground"
              aria-label="Liste leeren"
            >
              <Trash2 className="h-4.5 w-4.5" />
            </button>
          ) : undefined
        }
      />
      <div className="bg-surface px-4">
        <Tabs options={TABS} value={tab} onChange={setTab} />
      </div>

      {tab === "optimiert" && (
        <div className="space-y-3 px-4 pt-4">
          {(features.isLoading || trip.isLoading) && <SkeletonList count={3} />}
          {trip.isError && <ErrorState onRetry={() => trip.refetch()} />}
          {!features.isLoading && !trip.isLoading && !optimizationEnabled && (
            <section className="card-surface p-5 text-center">
              <span className="mx-auto grid h-10 w-10 place-items-center rounded-xl bg-primary-soft text-primary">
                <Clock3 className="h-5 w-5" />
              </span>
              <h2 className="mt-3 text-[15px] font-semibold text-navy">Einkaufsoptimierung wird vorbereitet</h2>
              <p className="mx-auto mt-1 max-w-[300px] text-[12px] leading-relaxed text-muted-foreground">
                Deine Einkaufsliste funktioniert bereits. Sobald mehrere geprüfte Märkte und belastbare Vergleichspreise verfügbar sind, schaltet Lokero die optimale Marktkombination frei.
              </p>
              <button
                type="button"
                onClick={() => setTab("meine")}
                className="mt-4 h-11 rounded-xl bg-primary px-4 text-[13px] font-semibold text-primary-foreground"
              >
                Meine Liste ansehen
              </button>
            </section>
          )}
          {optimizationEnabled && trip.data && (
            <>
              <OptimizedTripSummary trip={trip.data} />
              <TripRouteRow trip={trip.data} />
              {trip.data.stops.map((s) => (
                <ShoppingMarketGroup key={s.marketId} stop={s} />
              ))}

              <button
                onClick={() => toast.success("Route wird in deiner Karten-App geöffnet")}
                className="flex h-13 w-full items-center justify-center gap-2 rounded-xl bg-primary py-3.5 text-[15px] font-semibold text-primary-foreground transition-transform duration-150 active:scale-[0.99]"
              >
                Route & Einkauf starten <ArrowRight className="h-4 w-4" />
              </button>
              <button
                onClick={() => toast.success("Liste gespeichert")}
                className="flex w-full items-center justify-center gap-2 py-1 text-[13px] font-medium text-muted-foreground"
              >
                <Save className="h-4 w-4" /> Liste als Einkaufsliste speichern
              </button>
            </>
          )}
        </div>
      )}

      {tab === "meine" && (
        <div className="space-y-2.5 px-4 pt-4">
          {listEntries.length === 0 && (
            <EmptyState
              icon={ListChecks}
              title="Deine Einkaufsliste ist noch leer."
              description="Füge Produkte hinzu, damit Lokero deinen Einkauf später optimieren kann."
              action={
                <Link
                  to="/angebote"
                  className="inline-flex h-11 items-center gap-1.5 rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground"
                >
                  <Plus className="h-4 w-4" /> Produkt hinzufügen
                </Link>
              }
            />
          )}
          {listEntries.map(({ productId, qty }) => {
            const product = getProduct(productId);
            if (!product) return null;
            const best = bestPriceFor(productId);
            const market = best ? getMarket(best.marketId) : undefined;
            return (
              <article key={productId} className="card-surface flex items-center gap-3 p-3">
                <ProductThumb categoryId={product.category} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-semibold text-navy">{product.name}</p>
                  <p className="truncate text-[11px] text-muted-foreground">
                    {product.brand} · {product.amount}
                  </p>
                  <div className="mt-1 flex items-center gap-1.5">
                    {market && <MarketLogo chain={market.chain} size="xs" />}
                    {best && (
                      <span className="tabular text-[12px] font-semibold text-navy">
                        {formatEuro(best.price)}
                      </span>
                    )}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1 rounded-xl bg-muted-surface p-1">
                  <button
                    onClick={() => setQty(productId, qty - 1)}
                    aria-label="Menge verringern"
                    className="grid h-8 w-8 place-items-center rounded-lg bg-surface text-navy"
                  >
                    <Minus className="h-3.5 w-3.5" />
                  </button>
                  <span className="tabular w-5 text-center text-[13px] font-semibold">{qty}</span>
                  <button
                    onClick={() => addToList(productId)}
                    aria-label="Menge erhöhen"
                    className="grid h-8 w-8 place-items-center rounded-lg bg-surface text-navy"
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}

import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { ArrowRight, Clock3, Heart, ListChecks, Minus, Plus, Save, Search, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/AppShell";
import { Tabs } from "@/components/lokero/FilterChips";
import { OptimizedTripSummary, ShoppingMarketGroup, TripRouteRow } from "@/components/lokero/OptimizedTrip";
import { ProductImage } from "@/components/lokero/ProductImage";
import { MarketLogo } from "@/components/lokero/MarketLogo";
import { EmptyState, ErrorState, SkeletonList } from "@/components/lokero/States";
import { useStore } from "@/lib/app-store";
import { bestPriceFor, fetchFeatures, fetchOptimizedTrip, getMarket, getProduct } from "@/services/lokero-api";
import { formatEuro, formatKm } from "@/lib/format";

export const Route = createFileRoute("/liste")({
  head: () => ({ meta: [{ title: "Einkaufsliste – Spareno" }] }),
  component: ListScreen,
});

const TABS = [{ id: "meine", label: "Liste" }, { id: "optimiert", label: "Optimiert" }];

type ListGroup = {
  key: string;
  marketId?: string;
  marketName: string;
  distanceKm: number;
  subtotal: number | null;
  entries: Array<{ productId: string; qty: number; price?: number }>;
};

function ListScreen() {
  const [tab, setTab] = useState("meine");
  const { listEntries, listCount, favoriteProducts, setQty, addToList, clearList } = useStore();
  const features = useQuery({ queryKey: ["lokero-features"], queryFn: fetchFeatures });
  const trip = useQuery({ queryKey: ["optimized-trip"], queryFn: fetchOptimizedTrip });
  const optimizationEnabled = features.data?.features.optimization !== false && trip.data?.enabled !== false;

  const groups = useMemo<ListGroup[]>(() => {
    const byMarket = new Map<string, ListGroup>();
    const unknown: ListGroup = { key: "unknown", marketName: "Noch kein Marktpreis", distanceKm: Number.POSITIVE_INFINITY, subtotal: null, entries: [] };
    for (const entry of listEntries) {
      const best = bestPriceFor(entry.productId);
      const market = best ? getMarket(best.marketId) : undefined;
      if (!best || !market) {
        unknown.entries.push(entry);
        continue;
      }
      const existing = byMarket.get(market.id) ?? { key: market.id, marketId: market.id, marketName: market.name, distanceKm: market.distanceKm, subtotal: 0, entries: [] };
      existing.entries.push({ ...entry, price: best.price });
      existing.subtotal = (existing.subtotal ?? 0) + best.price * entry.qty;
      byMarket.set(market.id, existing);
    }
    const result = Array.from(byMarket.values()).sort((a, b) => a.distanceKm - b.distanceKm);
    if (unknown.entries.length) result.push(unknown);
    return result;
  }, [listEntries]);

  const knownTotal = useMemo(
    () => groups.reduce((sum, group) => sum + (group.subtotal ?? 0), 0),
    [groups],
  );
  const hasUnknownPrices = groups.some((group) => group.subtotal == null);
  const quickFavorites = useMemo(
    () => favoriteProducts
      .filter((id) => !listEntries.some((entry) => entry.productId === id))
      .map((id) => getProduct(id))
      .filter((product): product is NonNullable<typeof product> => Boolean(product))
      .slice(0, 6),
    [favoriteProducts, listEntries],
  );

  return (
    <div>
      <PageHeader title="Einkaufsliste" action={listEntries.length > 0 ? <button onClick={() => { clearList(); toast.success("Liste geleert"); }} className="tap-target grid place-items-center rounded-xl text-muted-foreground" aria-label="Liste leeren"><Trash2 className="h-4.5 w-4.5" /></button> : undefined} />
      <div className="bg-surface px-4"><Tabs options={TABS} value={tab} onChange={setTab} /></div>

      {tab === "optimiert" && (
        <div className="space-y-3 px-4 pt-4">
          {(features.isLoading || trip.isLoading) && <SkeletonList count={3} />}
          {trip.isError && <ErrorState onRetry={() => trip.refetch()} />}
          {!features.isLoading && !trip.isLoading && !optimizationEnabled && (
            <section className="card-surface p-5 text-center">
              <span className="mx-auto grid h-10 w-10 place-items-center rounded-xl bg-primary-soft text-primary"><Clock3 className="h-5 w-5" /></span>
              <h2 className="mt-3 text-[15px] font-semibold text-navy">Einkaufsoptimierung wird vorbereitet</h2>
              <p className="mx-auto mt-1 max-w-[300px] text-[12px] leading-relaxed text-muted-foreground">Deine Einkaufsliste funktioniert bereits. Sobald mehrere geprüfte Märkte und belastbare Vergleichspreise verfügbar sind, schaltet Spareno die optimale Marktkombination frei.</p>
              <button type="button" onClick={() => setTab("meine")} className="mt-4 h-11 rounded-xl bg-primary px-4 text-[13px] font-semibold text-primary-foreground">Liste ansehen</button>
            </section>
          )}
          {optimizationEnabled && trip.data && <><OptimizedTripSummary trip={trip.data} /><TripRouteRow trip={trip.data} />{trip.data.stops.map((s) => <ShoppingMarketGroup key={s.marketId} stop={s} />)}<button onClick={() => toast.success("Route wird in deiner Karten-App geöffnet")} className="flex h-13 w-full items-center justify-center gap-2 rounded-xl bg-primary py-3.5 text-[15px] font-semibold text-primary-foreground">Route & Einkauf starten <ArrowRight className="h-4 w-4" /></button><button onClick={() => toast.success("Liste gespeichert")} className="flex w-full items-center justify-center gap-2 py-1 text-[13px] font-medium text-muted-foreground"><Save className="h-4 w-4" /> Liste speichern</button></>}
        </div>
      )}

      {tab === "meine" && (
        <div className="space-y-4 px-4 pt-4">
          {listEntries.length > 0 && (
            <section className="card-surface flex items-center gap-3 p-4">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-primary-soft text-primary"><ListChecks className="h-5 w-5" /></span>
              <div className="min-w-0 flex-1">
                <p className="text-[13px] font-semibold text-navy">{listCount} {listCount === 1 ? "Artikel" : "Artikel"} auf deiner Liste</p>
                <p className="mt-0.5 text-[11px] text-muted-foreground">{hasUnknownPrices ? `Bekannte Preise: ${formatEuro(knownTotal)}` : `Aktuell günstigster Gesamtpreis: ${formatEuro(knownTotal)}`}</p>
              </div>
              <Link to="/suche" className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-border bg-surface text-navy" aria-label="Produkt hinzufügen"><Search className="h-4 w-4" /></Link>
            </section>
          )}

          {quickFavorites.length > 0 && (
            <section>
              <div className="mb-2 flex items-center gap-1.5"><Heart className="h-3.5 w-3.5 text-primary" /><h2 className="text-[12px] font-semibold text-navy">Aus deinen Favoriten hinzufügen</h2></div>
              <div className="flex gap-2 overflow-x-auto pb-1">
                {quickFavorites.map((product) => (
                  <button key={product.id} type="button" onClick={() => { addToList(product.id); toast.success(`${product.name} hinzugefügt`); }} className="flex min-w-[210px] items-center gap-2 rounded-2xl border border-border bg-surface p-2.5 text-left">
                    <ProductImage product={product} size="sm" />
                    <span className="min-w-0 flex-1 line-clamp-2 text-[12px] font-semibold leading-snug text-navy">{product.name}</span>
                    <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-primary-soft text-primary"><Plus className="h-4 w-4" /></span>
                  </button>
                ))}
              </div>
            </section>
          )}

          {listEntries.length === 0 && <EmptyState icon={ListChecks} title="Deine Einkaufsliste ist noch leer." description="Füge Produkte über Suche, Angebote oder deine Favoriten hinzu." action={<div className="flex flex-wrap justify-center gap-2"><Link to="/suche" className="inline-flex h-11 items-center gap-1.5 rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground"><Search className="h-4 w-4" /> Produkt suchen</Link><Link to="/angebote" className="inline-flex h-11 items-center gap-1.5 rounded-xl border border-border bg-surface px-4 text-sm font-semibold text-navy"><Plus className="h-4 w-4" /> Angebote ansehen</Link></div>} />}
          {groups.length > 1 && groups.some((group) => group.marketId) && <p className="text-[11px] text-muted-foreground">Märkte werden aktuell nach Entfernung sortiert. Eine echte Routenoptimierung folgt später.</p>}
          {groups.map((group) => {
            const market = group.marketId ? getMarket(group.marketId) : undefined;
            return (
              <section key={group.key} className="overflow-hidden rounded-2xl border border-border bg-surface">
                <div className="flex items-center gap-3 border-b border-border px-3 py-3">
                  {market && <MarketLogo chain={market.chain} size="sm" />}
                  <div className="min-w-0 flex-1"><h2 className="line-clamp-2 text-[13px] font-semibold leading-snug text-navy">{group.marketName}</h2>{market && <p className="text-[10px] text-muted-foreground">{formatKm(group.distanceKm)}</p>}</div>
                  {group.subtotal != null && <div className="shrink-0 text-right"><p className="text-[10px] text-muted-foreground">Zwischensumme</p><p className="tabular text-[14px] font-bold text-navy">{formatEuro(group.subtotal)}</p></div>}
                </div>
                <div className="divide-y divide-border">
                  {group.entries.map(({ productId, qty, price }) => {
                    const product = getProduct(productId);
                    if (!product) return null;
                    return (
                      <article key={productId} className="flex items-center gap-2.5 p-3">
                        <ProductImage product={product} size="sm" />
                        <div className="min-w-0 flex-1"><p className="line-clamp-2 text-[13px] font-semibold leading-snug text-navy">{product.name}</p>{price != null && <p className="tabular mt-1 text-[11px] text-muted-foreground">{formatEuro(price)} je Stück</p>}</div>
                        <button type="button" onClick={() => setQty(productId, 0)} aria-label={`${product.name} entfernen`} className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-muted-foreground"><Trash2 className="h-3.5 w-3.5" /></button>
                        <div className="flex shrink-0 items-center gap-1 rounded-xl bg-muted-surface p-1">
                          <button onClick={() => setQty(productId, qty - 1)} aria-label="Menge verringern" className="grid h-8 w-8 place-items-center rounded-lg bg-surface text-navy"><Minus className="h-3.5 w-3.5" /></button>
                          <span className="tabular w-5 text-center text-[13px] font-semibold">{qty}</span>
                          <button onClick={() => addToList(productId)} aria-label="Menge erhöhen" className="grid h-8 w-8 place-items-center rounded-lg bg-surface text-navy"><Plus className="h-3.5 w-3.5" /></button>
                        </div>
                      </article>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}

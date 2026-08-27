import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState, type FormEvent } from "react";
import { ArrowRight, Check, Clock3, Heart, ListChecks, Minus, Play, Plus, RotateCcw, Save, Search, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/AppShell";
import { Tabs } from "@/components/lokero/FilterChips";
import { OptimizedTripSummary, ShoppingMarketGroup, TripRouteRow } from "@/components/lokero/OptimizedTrip";
import { ProductImage } from "@/components/lokero/ProductImage";
import { MarketLogo } from "@/components/lokero/MarketLogo";
import { EmptyState, ErrorState, SkeletonList } from "@/components/lokero/States";
import { manualListKey, useStore } from "@/lib/app-store";
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
  const [shoppingMode, setShoppingMode] = useState(false);
  const [manualName, setManualName] = useState("");
  const {
    listEntries,
    listCount,
    manualListItems,
    checkedListItems,
    favoriteProducts,
    setQty,
    addToList,
    addManualListItem,
    setManualListQty,
    removeManualListItem,
    clearList,
    toggleListChecked,
    clearCheckedList,
  } = useStore();
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
  const totalCount = listCount + manualListItems.reduce((sum, item) => sum + item.qty, 0);
  const totalPositions = listEntries.length + manualListItems.length;
  const hasAnyItems = totalPositions > 0;
  const hasUnknownPrices = manualListItems.length > 0 || groups.some((group) => group.subtotal == null);
  const checkedProductCount = listEntries.filter((entry) => checkedListItems.includes(entry.productId)).length;
  const checkedManualCount = manualListItems.filter((item) => checkedListItems.includes(manualListKey(item.id))).length;
  const checkedCount = checkedProductCount + checkedManualCount;
  const progress = totalPositions > 0 ? Math.round((checkedCount / totalPositions) * 100) : 0;
  const allChecked = totalPositions > 0 && checkedCount === totalPositions;
  const priceSummary = hasUnknownPrices
    ? knownTotal > 0
      ? `Bekannte Preise: ${formatEuro(knownTotal)}`
      : "Für diese Liste fehlen noch Vergleichspreise."
    : `Aktuell günstigster Gesamtpreis: ${formatEuro(knownTotal)}`;
  const quickFavorites = useMemo(
    () => favoriteProducts
      .filter((id) => !listEntries.some((entry) => entry.productId === id))
      .map((id) => getProduct(id))
      .filter((product): product is NonNullable<typeof product> => Boolean(product))
      .slice(0, 6),
    [favoriteProducts, listEntries],
  );

  const toggleShoppingMode = () => {
    setShoppingMode((active) => !active);
    if (!shoppingMode) toast.success(checkedCount > 0 ? "Einkauf fortgesetzt" : "Einkaufsmodus gestartet");
  };

  const changeTab = (nextTab: string) => {
    if (nextTab !== "meine") setShoppingMode(false);
    setTab(nextTab);
  };

  const confirmClearList = () => {
    if (!window.confirm("Möchtest du wirklich die komplette Einkaufsliste leeren?")) return;
    clearList();
    setShoppingMode(false);
    toast.success("Liste geleert");
  };

  const submitManualItem = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const name = manualName.trim();
    if (!name) return;
    addManualListItem(name);
    setManualName("");
    toast.success(`${name} hinzugefügt`);
  };

  return (
    <div>
      <PageHeader title="Einkaufsliste" action={hasAnyItems ? <button type="button" onClick={confirmClearList} className="tap-target grid place-items-center rounded-xl text-muted-foreground" aria-label="Liste leeren"><Trash2 className="h-4.5 w-4.5" /></button> : undefined} />
      <div className="bg-surface px-4"><Tabs options={TABS} value={tab} onChange={changeTab} /></div>

      {tab === "optimiert" && (
        <div className="space-y-3 px-4 pt-4">
          {(features.isLoading || trip.isLoading) && <SkeletonList count={3} />}
          {trip.isError && <ErrorState onRetry={() => trip.refetch()} />}
          {!features.isLoading && !trip.isLoading && !optimizationEnabled && (
            <section className="card-surface p-5 text-center">
              <span className="mx-auto grid h-10 w-10 place-items-center rounded-xl bg-primary-soft text-primary"><Clock3 className="h-5 w-5" /></span>
              <h2 className="mt-3 text-[15px] font-semibold text-navy">Einkaufsoptimierung wird vorbereitet</h2>
              <p className="mx-auto mt-1 max-w-[300px] text-[12px] leading-relaxed text-muted-foreground">Deine Einkaufsliste funktioniert bereits. Sobald mehrere geprüfte Märkte und belastbare Vergleichspreise verfügbar sind, schaltet Spareno die optimale Marktkombination frei.</p>
              <button type="button" onClick={() => changeTab("meine")} className="mt-4 h-11 rounded-xl bg-primary px-4 text-[13px] font-semibold text-primary-foreground">Liste ansehen</button>
            </section>
          )}
          {optimizationEnabled && trip.data && <><OptimizedTripSummary trip={trip.data} /><TripRouteRow trip={trip.data} />{trip.data.stops.map((s) => <ShoppingMarketGroup key={s.marketId} stop={s} />)}<button type="button" onClick={() => toast.success("Route wird in deiner Karten-App geöffnet")} className="flex h-13 w-full items-center justify-center gap-2 rounded-xl bg-primary py-3.5 text-[15px] font-semibold text-primary-foreground">Route & Einkauf starten <ArrowRight className="h-4 w-4" /></button><button type="button" onClick={() => toast.success("Liste gespeichert")} className="flex w-full items-center justify-center gap-2 py-1 text-[13px] font-medium text-muted-foreground"><Save className="h-4 w-4" /> Liste speichern</button></>}
        </div>
      )}

      {tab === "meine" && (
        <div className="space-y-4 px-4 pt-4">
          {hasAnyItems && (
            <section className="card-surface p-4">
              <div className="flex items-center gap-3">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-primary-soft text-primary"><ListChecks className="h-5 w-5" /></span>
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] font-semibold text-navy">{shoppingMode ? `${checkedCount} von ${totalPositions} Positionen erledigt` : `${totalCount} Artikel auf deiner Liste`}</p>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">{shoppingMode ? "Tippe Produkte an, sobald sie im Wagen liegen." : priceSummary}</p>
                </div>
                {!shoppingMode && <Link to="/suche" className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-border bg-surface text-navy" aria-label="Produkt hinzufügen"><Search className="h-4 w-4" /></Link>}
              </div>

              {shoppingMode && (
                <div className="mt-3" aria-live="polite">
                  <div className="h-2 overflow-hidden rounded-full bg-muted-surface" role="progressbar" aria-label="Einkaufsfortschritt" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><div className="h-full rounded-full bg-primary transition-all" style={{ width: `${progress}%` }} /></div>
                  <div className="mt-2 flex items-center justify-between text-[11px]"><span className="font-medium text-primary">{progress}% erledigt</span><button type="button" onClick={clearCheckedList} disabled={checkedCount === 0} className="inline-flex items-center gap-1 text-muted-foreground disabled:opacity-40"><RotateCcw className="h-3 w-3" /> Zurücksetzen</button></div>
                </div>
              )}

              <button type="button" onClick={toggleShoppingMode} className={`mt-3 flex h-11 w-full items-center justify-center gap-2 rounded-xl text-[13px] font-semibold ${shoppingMode ? "border border-border bg-surface text-navy" : "bg-primary text-primary-foreground"}`}>
                {shoppingMode ? <><Check className="h-4 w-4" /> Einkaufsmodus beenden</> : <><Play className="h-4 w-4" /> {checkedCount > 0 ? "Einkauf fortsetzen" : "Einkauf starten"}</>}
              </button>
            </section>
          )}

          {shoppingMode && allChecked && (
            <section className="rounded-2xl border border-primary/20 bg-primary-soft p-4 text-center" aria-live="polite">
              <span className="mx-auto grid h-10 w-10 place-items-center rounded-full bg-primary text-primary-foreground"><Check className="h-5 w-5" /></span>
              <h2 className="mt-2 text-[14px] font-semibold text-navy">Einkauf geschafft</h2>
              <p className="mt-1 text-[11px] text-muted-foreground">Alle Positionen deiner Liste sind abgehakt.</p>
            </section>
          )}

          {!shoppingMode && (
            <form onSubmit={submitManualItem} className="rounded-2xl border border-border bg-surface p-3">
              <label htmlFor="manual-list-item" className="mb-2 block text-[12px] font-semibold text-navy">Artikel frei hinzufügen</label>
              <div className="flex gap-2">
                <input id="manual-list-item" value={manualName} onChange={(event) => setManualName(event.target.value)} placeholder="z. B. Müllbeutel" maxLength={80} autoComplete="off" enterKeyHint="done" className="h-11 min-w-0 flex-1 rounded-xl border border-border bg-muted-surface px-3 text-[13px] text-navy outline-none placeholder:text-muted-foreground focus:border-primary" />
                <button type="submit" disabled={!manualName.trim()} className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-primary text-primary-foreground disabled:opacity-40" aria-label="Freien Artikel hinzufügen"><Plus className="h-4 w-4" /></button>
              </div>
              <p className="mt-2 text-[10px] leading-relaxed text-muted-foreground">Für Dinge, die Spareno nicht als Produkt kennt. Sie bleiben auf diesem Gerät gespeichert.</p>
            </form>
          )}

          {!shoppingMode && quickFavorites.length > 0 && (
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

          {!hasAnyItems && <EmptyState icon={ListChecks} title="Deine Einkaufsliste ist noch leer." description="Füge einen freien Artikel ein oder wähle ein Produkt über Suche, Angebote oder Favoriten." action={<div className="flex flex-wrap justify-center gap-2"><Link to="/suche" className="inline-flex h-11 items-center gap-1.5 rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground"><Search className="h-4 w-4" /> Produkt suchen</Link><Link to="/angebote" className="inline-flex h-11 items-center gap-1.5 rounded-xl border border-border bg-surface px-4 text-sm font-semibold text-navy"><Plus className="h-4 w-4" /> Angebote ansehen</Link></div>} />}
          {groups.length > 1 && groups.some((group) => group.marketId) && !shoppingMode && <p className="text-[11px] text-muted-foreground">Märkte werden aktuell nach Entfernung sortiert. Eine echte Routenoptimierung folgt später.</p>}
          {groups.map((group) => {
            const market = group.marketId ? getMarket(group.marketId) : undefined;
            const displayEntries = shoppingMode
              ? [...group.entries].sort((a, b) => Number(checkedListItems.includes(a.productId)) - Number(checkedListItems.includes(b.productId)))
              : group.entries;
            return (
              <section key={group.key} className="overflow-hidden rounded-2xl border border-border bg-surface">
                <div className="flex items-center gap-3 border-b border-border px-3 py-3">
                  {market && <MarketLogo chain={market.chain} size="sm" />}
                  <div className="min-w-0 flex-1"><h2 className="line-clamp-2 text-[13px] font-semibold leading-snug text-navy">{group.marketName}</h2>{market && <p className="text-[10px] text-muted-foreground">{formatKm(group.distanceKm)}</p>}</div>
                  {group.subtotal != null && !shoppingMode && <div className="shrink-0 text-right"><p className="text-[10px] text-muted-foreground">Zwischensumme</p><p className="tabular text-[14px] font-bold text-navy">{formatEuro(group.subtotal)}</p></div>}
                  {shoppingMode && <p className="shrink-0 text-[11px] font-medium text-muted-foreground">{displayEntries.filter((entry) => checkedListItems.includes(entry.productId)).length}/{displayEntries.length}</p>}
                </div>
                <div className="divide-y divide-border">
                  {displayEntries.map(({ productId, qty, price }) => {
                    const product = getProduct(productId);
                    if (!product) return null;
                    const checked = checkedListItems.includes(productId);
                    return (
                      <article key={productId} className={`flex items-center gap-2.5 p-3 transition-opacity ${checked ? "opacity-55" : ""}`}>
                        {shoppingMode && (
                          <button type="button" onClick={() => toggleListChecked(productId)} aria-label={checked ? `${product.name} wieder öffnen` : `${product.name} abhaken`} className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl border ${checked ? "border-primary bg-primary text-primary-foreground" : "border-border bg-surface text-muted-foreground"}`}>
                            {checked && <Check className="h-4 w-4" />}
                          </button>
                        )}
                        <ProductImage product={product} size="sm" />
                        <button type="button" onClick={shoppingMode ? () => toggleListChecked(productId) : undefined} className={`min-w-0 flex-1 text-left ${shoppingMode ? "cursor-pointer" : "cursor-default"}`}>
                          <p className={`line-clamp-2 text-[13px] font-semibold leading-snug text-navy ${checked ? "line-through" : ""}`}>{product.name}</p>
                          <p className="tabular mt-1 text-[11px] text-muted-foreground">{qty > 1 ? `${qty} Stück` : "1 Stück"}{price != null ? ` · ${formatEuro(price)} je Stück` : ""}</p>
                        </button>
                        {!shoppingMode && <button type="button" onClick={() => setQty(productId, 0)} aria-label={`${product.name} entfernen`} className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-muted-foreground"><Trash2 className="h-3.5 w-3.5" /></button>}
                        {!shoppingMode && (
                          <div className="flex shrink-0 items-center gap-1 rounded-xl bg-muted-surface p-1">
                            <button type="button" onClick={() => setQty(productId, qty - 1)} aria-label="Menge verringern" className="grid h-8 w-8 place-items-center rounded-lg bg-surface text-navy"><Minus className="h-3.5 w-3.5" /></button>
                            <span className="tabular w-5 text-center text-[13px] font-semibold">{qty}</span>
                            <button type="button" onClick={() => addToList(productId)} aria-label="Menge erhöhen" className="grid h-8 w-8 place-items-center rounded-lg bg-surface text-navy"><Plus className="h-3.5 w-3.5" /></button>
                          </div>
                        )}
                      </article>
                    );
                  })}
                </div>
              </section>
            );
          })}

          {manualListItems.length > 0 && (
            <section className="overflow-hidden rounded-2xl border border-border bg-surface">
              <div className="flex items-center justify-between border-b border-border px-3 py-3">
                <div><h2 className="text-[13px] font-semibold text-navy">Weitere Artikel</h2><p className="text-[10px] text-muted-foreground">Manuell hinzugefügt · ohne Preisvergleich</p></div>
                {shoppingMode && <p className="text-[11px] font-medium text-muted-foreground">{checkedManualCount}/{manualListItems.length}</p>}
              </div>
              <div className="divide-y divide-border">
                {[...manualListItems]
                  .sort((a, b) => shoppingMode ? Number(checkedListItems.includes(manualListKey(a.id))) - Number(checkedListItems.includes(manualListKey(b.id))) : 0)
                  .map((item) => {
                    const itemKey = manualListKey(item.id);
                    const checked = checkedListItems.includes(itemKey);
                    return (
                      <article key={item.id} className={`flex items-center gap-2.5 p-3 transition-opacity ${checked ? "opacity-55" : ""}`}>
                        {shoppingMode && (
                          <button type="button" onClick={() => toggleListChecked(itemKey)} aria-label={checked ? `${item.name} wieder öffnen` : `${item.name} abhaken`} className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl border ${checked ? "border-primary bg-primary text-primary-foreground" : "border-border bg-surface text-muted-foreground"}`}>
                            {checked && <Check className="h-4 w-4" />}
                          </button>
                        )}
                        <button type="button" onClick={shoppingMode ? () => toggleListChecked(itemKey) : undefined} className={`min-w-0 flex-1 text-left ${shoppingMode ? "cursor-pointer" : "cursor-default"}`}>
                          <p className={`line-clamp-2 text-[13px] font-semibold leading-snug text-navy ${checked ? "line-through" : ""}`}>{item.name}</p>
                          <p className="mt-1 text-[11px] text-muted-foreground">{item.qty > 1 ? `${item.qty} Stück` : "1 Stück"}</p>
                        </button>
                        {!shoppingMode && <button type="button" onClick={() => removeManualListItem(item.id)} aria-label={`${item.name} entfernen`} className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-muted-foreground"><Trash2 className="h-3.5 w-3.5" /></button>}
                        {!shoppingMode && (
                          <div className="flex shrink-0 items-center gap-1 rounded-xl bg-muted-surface p-1">
                            <button type="button" onClick={() => setManualListQty(item.id, item.qty - 1)} aria-label="Menge verringern" className="grid h-8 w-8 place-items-center rounded-lg bg-surface text-navy"><Minus className="h-3.5 w-3.5" /></button>
                            <span className="tabular w-5 text-center text-[13px] font-semibold">{item.qty}</span>
                            <button type="button" onClick={() => setManualListQty(item.id, item.qty + 1)} aria-label="Menge erhöhen" className="grid h-8 w-8 place-items-center rounded-lg bg-surface text-navy"><Plus className="h-3.5 w-3.5" /></button>
                          </div>
                        )}
                      </article>
                    );
                  })}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}

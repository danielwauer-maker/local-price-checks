import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, CalendarDays, Clock3, Heart, ShoppingBasket, TrendingDown, TrendingUp } from "lucide-react";
import { PageHeader } from "@/components/AppShell";
import { useActiveMarketIds, useStore } from "@/lib/app-store";
import { MARKETS, PRODUCTS, currentOffers, formatEuro, type Price } from "@/data/demo";
import { groupIdenticalOffers, marketSummary, type GroupedOffer } from "@/lib/offer-groups";
import { withDeviceIdentity } from "@/lib/device-identity";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

export const Route = createFileRoute("/naechste-woche")({
  head: () => ({ meta: [{ title: "Nächste Woche – LocalPrices" }] }),
  component: NextWeekPage,
});

type UpcomingPayload = {
  count: number;
  startsOn: string | null;
  prices: Price[];
};

function euroDiff(value: number) {
  return formatEuro(Math.abs(value));
}

function NextWeekPage() {
  const activeIds = useActiveMarketIds();
  const { basket, toggleBasket, productFavorites, toggleProductFavorite } = useStore();
  const [payload, setPayload] = useState<UpcomingPayload>({ count: 0, startsOn: null, prices: [] });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    setLoading(true);
    fetch("/api/offers/upcoming", { headers: withDeviceIdentity() })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`upcoming ${response.status}`)))
      .then((data: UpcomingPayload) => live && setPayload(data))
      .catch((error) => {
        console.error("Upcoming offers failed", error);
        if (live) setPayload({ count: 0, startsOn: null, prices: [] });
      })
      .finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [activeIds.join(",")]);

  const current = useMemo(() => currentOffers(activeIds), [activeIds]);
  const currentBestByProduct = useMemo(() => {
    const map = new Map<string, number>();
    for (const row of current) {
      const price = row.price.offer!.price;
      const previous = map.get(row.product.id);
      if (previous == null || price < previous) map.set(row.product.id, price);
    }
    return map;
  }, [current]);

  const upcoming = useMemo<GroupedOffer[]>(() => {
    const raw = payload.prices.flatMap((price) => {
      const product = PRODUCTS.find((row) => row.id === price.productId);
      const market = MARKETS.find((row) => row.id === price.marketId);
      if (!product || !market || !activeIds.includes(market.id) || !price.offer) return [];
      const base = price.price > price.offer.price ? price.price : price.offer.price;
      const discount = base > 0 ? Math.max(0, Math.round((1 - price.offer.price / base) * 100)) : 0;
      return [{ product, market, price, discount }];
    });
    return groupIdenticalOffers(raw).sort((a, b) => {
      const av = (a.price as Price & { validFrom?: string }).validFrom || "";
      const bv = (b.price as Price & { validFrom?: string }).validFrom || "";
      return av.localeCompare(bv) || a.product.name.localeCompare(b.product.name, "de");
    });
  }, [payload.prices, activeIds]);

  const startsLabel = payload.startsOn
    ? new Date(`${payload.startsOn}T12:00:00`).toLocaleDateString("de-DE", { weekday: "short", day: "2-digit", month: "2-digit" })
    : null;

  return <div>
    <PageHeader title="Nächste Woche" subtitle={loading ? "Kommende Angebote werden geladen …" : upcoming.length ? `${upcoming.length} kommende Aktionen in deinen Märkten` : "Noch keine kommenden Angebote veröffentlicht"} />

    <div className="px-5">
      <Link to="/angebote" className="mb-3 inline-flex items-center gap-1 text-xs font-semibold text-primary"><ArrowLeft className="h-3.5 w-3.5" /> Aktuelle Angebote</Link>
      <div className="surface-card flex items-start gap-3 p-4">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-primary-soft text-primary"><CalendarDays className="h-5 w-5" /></span>
        <div><p className="text-sm font-semibold">Schon heute sehen, was bald günstiger wird</p><p className="mt-1 text-xs leading-relaxed text-muted-foreground">LocalPrices vergleicht kommende Prospektpreise mit den aktuell verfügbaren Angeboten. So siehst du, ob sich Warten lohnt.</p>{startsLabel && <p className="mt-2 flex items-center gap-1 text-xs font-semibold text-primary"><Clock3 className="h-3.5 w-3.5" /> Erste neue Angebote ab {startsLabel}</p>}</div>
      </div>
    </div>

    <section className="mt-4 space-y-3 px-5">
      {upcoming.map((offer) => {
        const currentBest = currentBestByProduct.get(offer.product.id);
        const nextPrice = offer.price.offer!.price;
        const diff = currentBest == null ? null : nextPrice - currentBest;
        const favorite = productFavorites.includes(offer.product.id);
        const inBasket = (basket[offer.product.id] ?? 0) > 0;
        const info = offer.price as Price & { validFrom?: string; validTo?: string };
        const start = info.validFrom ? new Date(`${info.validFrom}T12:00:00`).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" }) : null;
        const imageUrl = (offer.product as typeof offer.product & { imageUrl?: string | null }).imageUrl;
        return <article key={offer.key} className="surface-card p-4">
          <div className="flex gap-3">
            <div className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-2xl bg-surface-2 text-3xl">{imageUrl ? <img src={imageUrl} alt={offer.product.name} className="h-full w-full object-contain" /> : offer.product.emoji}</div>
            <div className="min-w-0 flex-1">
              <div className="flex items-start justify-between gap-2"><div className="min-w-0"><p className="truncate text-sm font-semibold">{offer.product.name}</p><p className="text-xs text-muted-foreground">{offer.product.brand}{offer.product.unit ? ` · ${offer.product.unit}` : ""}</p></div><p className="tabular text-lg font-bold text-deal">{formatEuro(nextPrice)}</p></div>
              <p className="mt-1 text-[11px] text-muted-foreground">{marketSummary(offer.markets)}{start ? ` · ab ${start}` : ""} · bis {offer.price.offer!.until}</p>
              {diff != null && Math.abs(diff) >= 0.01 && <div className={cn("mt-2 flex items-center gap-1 rounded-xl px-2.5 py-1.5 text-xs font-semibold", diff < 0 ? "bg-primary-soft text-primary" : "bg-amber-50 text-amber-800")}>
                {diff < 0 ? <TrendingDown className="h-3.5 w-3.5" /> : <TrendingUp className="h-3.5 w-3.5" />}
                {diff < 0 ? `Warten lohnt: ${euroDiff(diff)} günstiger` : `Diese Woche ist ${euroDiff(diff)} günstiger`}
              </div>}
              {diff != null && Math.abs(diff) < 0.01 && <p className="mt-2 text-xs font-medium text-muted-foreground">Preis ist diese und nächste Woche gleich.</p>}
              {currentBest == null && <p className="mt-2 text-xs font-medium text-primary">Neu im kommenden Angebotszeitraum.</p>}
            </div>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 border-t border-border pt-3">
            <button onClick={() => toggleProductFavorite(offer.product.id)} className={cn("flex items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-xs font-semibold", favorite ? "bg-deal/10 text-deal" : "bg-secondary text-muted-foreground")}><Heart className={cn("h-4 w-4", favorite && "fill-current")} /> {favorite ? "Favorit" : "Merken"}</button>
            <button onClick={() => { toggleBasket(offer.product.id); toast.success(inBasket ? `${offer.product.name} von der Liste entfernt` : `${offer.product.name} auf der Liste`); }} className={cn("flex items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-xs font-semibold", inBasket ? "bg-primary-soft text-primary" : "bg-secondary text-muted-foreground")}><ShoppingBasket className="h-4 w-4" /> {inBasket ? "Auf Liste" : "Zur Liste"}</button>
          </div>
        </article>;
      })}

      {!loading && activeIds.length === 0 && <div className="surface-card p-6 text-center text-sm text-muted-foreground">Wähle zuerst mindestens einen freigegebenen Markt aus.</div>}
      {!loading && activeIds.length > 0 && upcoming.length === 0 && <div className="surface-card p-6 text-center"><p className="text-sm font-semibold">Noch nichts für nächste Woche veröffentlicht</p><p className="mt-1 text-xs text-muted-foreground">Sobald deine Märkte kommende Angebote bereitstellen und sie geprüft sind, erscheinen sie automatisch hier.</p></div>}
    </section>
  </div>;
}

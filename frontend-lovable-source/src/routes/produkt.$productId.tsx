import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Bell, Check, ChevronLeft, Heart, LineChart, ShoppingCart } from "lucide-react";
import { toast } from "sonner";
import { ProductImage } from "@/components/lokero/ProductImage";
import { MarketLogo } from "@/components/lokero/MarketLogo";
import { DiscountBadge } from "@/components/lokero/DiscountBadge";
import { AlternativeCard } from "@/components/lokero/FavoriteCard";
import { EmptyState } from "@/components/lokero/States";
import { useStore } from "@/lib/app-store";
import { alternativesFor, bestPriceFor, fetchFeatures, getCategory, getMarket, getOfferFor, getProduct, marketPricesFor } from "@/services/lokero-api";
import { formatEuro, formatKm } from "@/lib/format";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/produkt/$productId")({
  head: ({ params }) => {
    const product = getProduct(params.productId);
    return { meta: [{ title: product ? `${product.name} – Preise & Angebote | Spareno` : "Produkt – Spareno" }] };
  },
  component: ProductScreen,
});

function ProductScreen() {
  const { productId } = Route.useParams();
  const navigate = useNavigate();
  const {
    list,
    addToList,
    isFavoriteProduct,
    toggleFavoriteProduct,
    alerts,
    setAlert,
    removeAlert,
  } = useStore();
  const features = useQuery({ queryKey: ["lokero-features"], queryFn: fetchFeatures });
  const product = getProduct(productId);

  if (!product) return <div className="px-4 pt-6"><EmptyState icon={LineChart} title="Produkt nicht gefunden" /></div>;

  const offer = getOfferFor(productId);
  const best = bestPriceFor(productId);
  const prices = marketPricesFor(productId);
  const alternatives = alternativesFor(productId);
  const alert = alerts[productId];
  const fav = isFavoriteProduct(productId);
  const onList = Number(list[productId] ?? 0) > 0;
  const priceAlertsEnabled = features.data?.features.price_alerts === true;
  const productAlternativesEnabled = features.data?.features.product_alternatives === true;
  const productMeta = [product.brand, product.detail ?? product.amount].filter(Boolean).join(" · ");

  const goBack = () => {
    if (typeof window !== "undefined" && window.history.length > 1) {
      window.history.back();
      return;
    }
    navigate({ to: "/angebote" });
  };

  return (
    <div className="pb-6">
      <header className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 bg-surface px-4 pb-3 pt-[max(1rem,env(safe-area-inset-top))]">
        <button onClick={goBack} aria-label="Zurück" className="tap-target grid place-items-center rounded-xl text-navy"><ChevronLeft className="h-5 w-5" /></button>
        <p className="truncate text-center text-[13px] font-semibold text-navy">Produkt</p>
        <button onClick={() => toggleFavoriteProduct(productId)} aria-pressed={fav} aria-label={fav ? "Favorit entfernen" : "Als Favorit merken"} className="tap-target grid place-items-center rounded-xl">
          <Heart className={cn("h-5 w-5 transition-all duration-150", fav ? "fill-discount text-discount" : "text-discount")} />
        </button>
      </header>

      <div className="space-y-3 px-4 pt-3">
        <section className="card-surface p-4 text-center">
          <ProductImage product={product} size="lg" className="mx-auto" eager />
          <h1 className="mt-3 text-[18px] font-bold leading-snug text-navy">{product.name}</h1>
          {productMeta && <p className="mt-1 text-[12px] text-muted-foreground">{productMeta}</p>}
          <p className="mt-1 text-[11px] text-muted-foreground">{getCategory(product.category)?.label}</p>

          {best && (
            <>
              <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
                <span className="tabular text-[28px] font-bold text-navy">{formatEuro(best.price)}</span>
                {offer?.oldPrice && <span className="tabular text-[13px] text-muted-foreground line-through">{formatEuro(offer.oldPrice)}</span>}
                {offer?.discount != null && <DiscountBadge value={offer.discount} />}
              </div>
              {offer?.basePrice && <p className="tabular mt-1 text-[11px] text-muted-foreground">{offer.basePrice}</p>}
            </>
          )}

          <div className="mt-4 flex items-stretch gap-2">
            <button
              type="button"
              disabled={onList}
              onClick={() => {
                addToList(productId);
                toast.success(`${product.name} auf deiner Liste`);
              }}
              className={cn(
                "flex min-h-12 flex-1 items-center justify-center gap-2 rounded-xl px-4 text-[13px] font-semibold transition-all",
                onList
                  ? "border border-primary/20 bg-primary-soft text-primary"
                  : "bg-primary text-primary-foreground active:scale-[0.99]",
              )}
            >
              {onList ? <Check className="h-4.5 w-4.5" /> : <ShoppingCart className="h-4.5 w-4.5" />}
              {onList ? "Auf deiner Einkaufsliste" : "Zur Einkaufsliste"}
            </button>

            {priceAlertsEnabled && (
              <button
                onClick={() => {
                  if (alert) { removeAlert(productId); toast.success("Preisalarm entfernt"); }
                  else { const target = Math.round((best?.price ?? 1) * 0.9 * 100) / 100; setAlert(productId, target, true); toast.success(`Preisalarm bei ${formatEuro(target)} aktiv`); }
                }}
                aria-pressed={!!alert}
                aria-label="Preisalarm"
                className={cn("grid h-12 w-12 shrink-0 place-items-center rounded-xl border", alert ? "border-alert bg-alert text-alert-foreground" : "border-border bg-surface text-muted-foreground")}
              ><Bell className="h-4.5 w-4.5" /></button>
            )}
          </div>
        </section>

        {productAlternativesEnabled && alternatives.length > 0 && (
          <section>
            <h2 className="mb-2 text-[13px] font-semibold text-navy">Ähnliche Produkte</h2>
            <div className="space-y-2">{alternatives.map((a) => { const alt = getProduct(a.alternativeProductId); if (!alt) return null; return <div key={a.alternativeProductId} className="card-surface overflow-hidden"><AlternativeCard product={alt} price={a.price} comparePrice={best?.price} kind={a.kind} /></div>; })}</div>
          </section>
        )}

        <section>
          <h2 className="mb-2 text-[13px] font-semibold text-navy">Preise in deiner Nähe</h2>
          <div className="card-surface divide-y divide-border">
            {prices.length === 0 && <p className="px-3 py-4 text-[12px] text-muted-foreground">Für dieses Produkt liegen aktuell keine Marktpreise vor.</p>}
            {prices.map((p) => {
              const m = getMarket(p.marketId);
              if (!m) return null;
              return (
                <div key={p.marketId} className="flex items-center gap-3 px-3 py-3">
                  <MarketLogo chain={m.chain} size="sm" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[12px] font-semibold text-navy">{m.name}</p>
                    <p className="tabular mt-0.5 text-[11px] text-muted-foreground">{formatKm(m.distanceKm)}</p>
                  </div>
                  <span className="tabular shrink-0 text-[15px] font-bold text-navy">{formatEuro(p.price)}</span>
                </div>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}

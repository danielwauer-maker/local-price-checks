import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Bell, ChevronLeft, Heart, LineChart, Plus } from "lucide-react";
import { toast } from "sonner";
import { ProductThumb } from "@/components/lokero/CategoryIcon";
import { MarketLogo } from "@/components/lokero/MarketLogo";
import { DiscountBadge } from "@/components/lokero/DiscountBadge";
import { AlternativeCard } from "@/components/lokero/FavoriteCard";
import { EmptyState } from "@/components/lokero/States";
import { useStore } from "@/lib/app-store";
import {
  alternativesFor,
  bestPriceFor,
  getCategory,
  getMarket,
  getOfferFor,
  getProduct,
  marketPricesFor,
} from "@/services/lokero-api";
import { formatDateRange, formatEuro, formatKm } from "@/lib/format";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/produkt/$productId")({
  head: ({ params }) => {
    const product = getProduct(params.productId);
    const title = product ? `${product.name} – Preise & Angebote | Lokero` : "Produkt – Lokero";
    const description = product
      ? `${product.name} von ${product.brand}: aktueller bester Preis, Grundpreis, Märkte in deiner Nähe und günstigere Alternativen.`
      : "Produktdetails mit Preisen aus deinen lokalen Märkten.";
    return {
      meta: [
        { title },
        { name: "description", content: description },
        { property: "og:title", content: title },
        { property: "og:description", content: description },
      ],
    };
  },
  component: ProductScreen,
});

function ProductScreen() {
  const { productId } = Route.useParams();
  const navigate = useNavigate();
  const { addToList, isFavoriteProduct, toggleFavoriteProduct, alerts, setAlert, removeAlert } =
    useStore();

  const product = getProduct(productId);
  if (!product) {
    return (
      <div className="px-4 pt-6">
        <EmptyState icon={LineChart} title="Produkt nicht gefunden" />
      </div>
    );
  }

  const offer = getOfferFor(productId);
  const best = bestPriceFor(productId);
  const bestMarket = best ? getMarket(best.marketId) : undefined;
  const prices = marketPricesFor(productId);
  const alternatives = alternativesFor(productId);
  const alert = alerts[productId];
  const fav = isFavoriteProduct(productId);

  return (
    <div className="pb-6">
      <header className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 bg-surface px-4 pb-3 pt-[max(1rem,env(safe-area-inset-top))]">
        <button
          onClick={() => navigate({ to: "/angebote" })}
          aria-label="Zurück"
          className="tap-target grid place-items-center rounded-xl text-navy"
        >
          <ChevronLeft className="h-5 w-5" />
        </button>
        <p className="truncate text-center text-[13px] font-semibold text-navy">Produkt</p>
        <button
          onClick={() => toggleFavoriteProduct(productId)}
          aria-pressed={fav}
          aria-label={fav ? "Favorit entfernen" : "Als Favorit merken"}
          className="tap-target grid place-items-center rounded-xl"
        >
          <Heart
            className={cn(
              "h-5 w-5 transition-all duration-150",
              fav ? "fill-discount text-discount" : "text-muted-foreground",
            )}
          />
        </button>
      </header>

      <div className="space-y-3 px-4 pt-3">
        <section className="card-surface p-4 text-center">
          <ProductThumb categoryId={product.category} size="lg" className="mx-auto" />
          <h1 className="mt-3 text-[18px] font-bold text-navy">{product.name}</h1>
          <p className="mt-0.5 text-[12px] text-muted-foreground">
            {product.brand} · {product.detail ?? product.amount}
          </p>
          <p className="mt-1 text-[11px] text-muted-foreground">
            {getCategory(product.category)?.label}
          </p>

          <div className="mt-3 flex items-center justify-center gap-2">
            <span className="tabular text-[26px] font-bold text-navy">
              {best ? formatEuro(best.price) : "–"}
            </span>
            {offer?.oldPrice && (
              <span className="tabular text-[13px] text-muted-foreground line-through">
                {formatEuro(offer.oldPrice)}
              </span>
            )}
            {offer?.discount != null && <DiscountBadge value={offer.discount} />}
          </div>
          {offer?.basePrice && (
            <p className="tabular mt-1 text-[11px] text-muted-foreground">{offer.basePrice}</p>
          )}
          {bestMarket && (
            <p className="mt-2 flex items-center justify-center gap-1.5 text-[12px] text-muted-foreground">
              <MarketLogo chain={bestMarket.chain} size="xs" /> {bestMarket.name} ·{" "}
              {formatKm(bestMarket.distanceKm)}
            </p>
          )}
          {offer && (
            <p className="tabular mt-1 text-[11px] text-muted-foreground">
              Angebot {formatDateRange(offer.validFrom, offer.validUntil)}
              {offer.leafletPage ? ` · Prospekt S. ${offer.leafletPage}` : ""}
            </p>
          )}

          <div className="mt-4 grid grid-cols-[minmax(0,1fr)_auto] gap-2">
            <button
              onClick={() => {
                addToList(productId);
                toast.success(`${product.name} auf deiner Liste`);
              }}
              className="flex h-12 items-center justify-center gap-2 rounded-xl bg-primary text-[14px] font-semibold text-primary-foreground transition-transform duration-150 active:scale-[0.99]"
            >
              <Plus className="h-4 w-4" /> Zur Einkaufsliste
            </button>
            <button
              onClick={() => {
                if (alert) {
                  removeAlert(productId);
                  toast.success("Preisalarm entfernt");
                } else {
                  const target = Math.round((best?.price ?? 1) * 0.9 * 100) / 100;
                  setAlert(productId, target, true);
                  toast.success(`Preisalarm bei ${formatEuro(target)} aktiv`);
                }
              }}
              aria-pressed={!!alert}
              aria-label="Preisalarm"
              className={cn(
                "grid h-12 w-12 place-items-center rounded-xl border",
                alert
                  ? "border-alert bg-alert text-alert-foreground"
                  : "border-border bg-surface text-muted-foreground",
              )}
            >
              <Bell className="h-4.5 w-4.5" />
            </button>
          </div>
        </section>

        {alternatives.length > 0 && (
          <section>
            <h2 className="mb-2 text-[13px] font-semibold text-navy">Ähnliche Produkte</h2>
            <div className="space-y-2">
              {alternatives.map((a) => {
                const alt = getProduct(a.alternativeProductId);
                if (!alt) return null;
                return (
                  <div key={a.alternativeProductId} className="card-surface overflow-hidden">
                    <AlternativeCard
                      product={alt}
                      price={a.price}
                      comparePrice={best?.price}
                      kind={a.kind}
                    />
                  </div>
                );
              })}
            </div>
          </section>
        )}

        <section>
          <h2 className="mb-2 text-[13px] font-semibold text-navy">Preise in deiner Nähe</h2>
          <div className="card-surface divide-y divide-border">
            {prices.length === 0 && (
              <p className="px-3 py-4 text-[12px] text-muted-foreground">
                Für dieses Produkt liegen aktuell keine Marktpreise vor.
              </p>
            )}
            {prices.map((p) => {
              const m = getMarket(p.marketId);
              if (!m) return null;
              return (
                <div key={p.marketId} className="flex items-center gap-3 px-3 py-2.5">
                  <MarketLogo chain={m.chain} size="sm" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[12px] font-medium text-navy">{m.name}</p>
                    <p className="tabular text-[11px] text-muted-foreground">
                      {formatKm(m.distanceKm)}
                    </p>
                  </div>
                  <span className="tabular text-[13px] font-semibold text-navy">
                    {formatEuro(p.price)}
                  </span>
                </div>
              );
            })}
          </div>
        </section>

        <section className="card-surface flex items-center gap-3 px-3 py-3 text-[12px] text-muted-foreground">
          <LineChart className="h-4 w-4 shrink-0 text-info" />
          Preisverlauf wird verfügbar, sobald genügend Preisdaten vorliegen.
        </section>
      </div>
    </div>
  );
}

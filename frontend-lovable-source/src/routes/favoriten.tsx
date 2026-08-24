import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Bell, Heart, Store } from "lucide-react";
import { PageHeader } from "@/components/AppShell";
import { Tabs } from "@/components/lokero/FilterChips";
import { AlternativeCard, FavoriteCard, PriceAlertCard } from "@/components/lokero/FavoriteCard";
import { MarketCard } from "@/components/lokero/MarketCard";
import { EmptyState, SkeletonList } from "@/components/lokero/States";
import { useStore } from "@/lib/app-store";
import {
  alternativesFor,
  fetchFavoriteMarkets,
  fetchFavoriteProducts,
  fetchFeatures,
  getMarket,
  getProduct,
} from "@/services/lokero-api";

export const Route = createFileRoute("/favoriten")({
  head: () => ({
    meta: [
      { title: "Favoriten & Preisalarme – Lokero" },
      {
        name: "description",
        content:
          "Beobachte deine Lieblingsprodukte und Märkte, entdecke günstigere Alternativen und setze Preisalarme mit Zielpreis.",
      },
    ],
  }),
  component: FavoritesScreen,
});

const TABS = [
  { id: "produkte", label: "Produkte" },
  { id: "maerkte", label: "Märkte" },
  { id: "alarm", label: "Preisalarm" },
];

function FavoritesScreen() {
  const [tab, setTab] = useState("produkte");
  const {
    favoriteProducts,
    favoriteMarkets,
    toggleFavoriteProduct,
    toggleFavoriteMarket,
    alerts,
    setAlert,
  } = useStore();

  const features = useQuery({ queryKey: ["lokero-features"], queryFn: fetchFeatures });
  const products = useQuery({ queryKey: ["favorite-products"], queryFn: fetchFavoriteProducts });
  const markets = useQuery({ queryKey: ["favorite-markets"], queryFn: fetchFavoriteMarkets });
  const flags = features.data?.features;
  const alternativesEnabled = flags?.product_alternatives !== false;
  const priceAlertsEnabled = flags?.price_alerts !== false;

  const rows = (products.data ?? []).filter((f) => favoriteProducts.includes(f.productId));

  return (
    <div>
      <PageHeader title="Favoriten" />
      <div className="bg-surface px-4">
        <Tabs options={TABS} value={tab} onChange={setTab} />
      </div>

      <div className="px-4 pt-4">
        {tab === "produkte" && (
          <section>
            <h2 className="mb-2.5 text-[13px] font-semibold text-navy">Deine Favoriten</h2>
            {products.isLoading && <SkeletonList count={3} />}
            {products.isSuccess && rows.length === 0 && (
              <EmptyState
                icon={Heart}
                title="Noch keine Favoriten"
                description="Merke dir Produkte, um Preise zu beobachten."
                action={
                  <Link
                    to="/angebote"
                    className="inline-flex h-11 items-center rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground"
                  >
                    Produkte entdecken
                  </Link>
                }
              />
            )}
            <div className="space-y-3">
              {rows.map((f) => {
                const product = getProduct(f.productId);
                if (!product) return null;
                const alt = alternativesEnabled ? alternativesFor(f.productId)[0] : undefined;
                const altProduct = alt ? getProduct(alt.alternativeProductId) : undefined;
                const alert = priceAlertsEnabled ? alerts[f.productId] : undefined;
                return (
                  <div key={f.productId}>
                    <FavoriteCard
                      product={product}
                      market={getMarket(f.marketId)}
                      price={f.price}
                      isFavorite
                      onToggleFavorite={() => toggleFavoriteProduct(f.productId)}
                    />
                    {alt && altProduct && (
                      <AlternativeCard
                        product={altProduct}
                        price={alt.price}
                        comparePrice={f.price}
                        kind={alt.kind}
                      />
                    )}
                    {alert && (
                      <PriceAlertCard
                        targetPrice={alert.targetPrice}
                        currentPrice={f.price}
                        active={alert.active}
                        onToggle={() => setAlert(f.productId, alert.targetPrice, !alert.active)}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {tab === "maerkte" && (
          <section className="space-y-2.5">
            {markets.isLoading && <SkeletonList count={2} />}
            {markets.isSuccess && favoriteMarkets.length === 0 && (
              <EmptyState
                icon={Store}
                title="Noch keine Lieblingsmärkte"
                description="Markiere Märkte, damit Lokero deine Einkäufe darauf abstimmt."
                action={
                  <Link
                    to="/maerkte"
                    className="inline-flex h-11 items-center rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground"
                  >
                    Märkte ansehen
                  </Link>
                }
              />
            )}
            {(markets.data ?? [])
              .filter((m) => favoriteMarkets.includes(m.id))
              .map((m) => (
                <MarketCard
                  key={m.id}
                  market={m}
                  isFavorite
                  onToggleFavorite={() => toggleFavoriteMarket(m.id)}
                />
              ))}
          </section>
        )}

        {tab === "alarm" && (
          <section className="space-y-3">
            {!priceAlertsEnabled ? (
              <EmptyState
                icon={Bell}
                title="Preisalarme werden vorbereitet"
                description="Diese Funktion wird freigeschaltet, sobald die Preisbasis zuverlässig genug ist."
              />
            ) : (
              <>
                {Object.keys(alerts).length === 0 && (
                  <EmptyState icon={Bell} title="Kein Preisalarm aktiv" description="Setze einen Zielpreis, und Lokero meldet sich, sobald er erreicht ist." />
                )}
                {Object.entries(alerts).map(([productId, a]) => {
                  const product = getProduct(productId);
                  const fav = (products.data ?? []).find((f) => f.productId === productId);
                  if (!product) return null;
                  return (
                    <div key={productId}>
                      <FavoriteCard
                        product={product}
                        market={fav ? getMarket(fav.marketId) : undefined}
                        price={fav?.price ?? a.targetPrice}
                        isFavorite={favoriteProducts.includes(productId)}
                        onToggleFavorite={() => toggleFavoriteProduct(productId)}
                      />
                      <PriceAlertCard
                        targetPrice={a.targetPrice}
                        currentPrice={fav?.price}
                        active={a.active}
                        onToggle={() => setAlert(productId, a.targetPrice, !a.active)}
                      />
                    </div>
                  );
                })}
              </>
            )}
          </section>
        )}
      </div>
    </div>
  );
}

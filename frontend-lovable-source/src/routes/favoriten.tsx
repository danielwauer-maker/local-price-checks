import { createFileRoute } from "@tanstack/react-router";
import { Heart, Plus } from "lucide-react";
import { PageHeader } from "@/components/AppShell";
import { PRODUCTS, currentOffers, formatEuro } from "@/data/demo";
import { useActiveMarketIds, useStore } from "@/lib/app-store";
import { toast } from "sonner";

export const Route = createFileRoute("/favoriten")({
  component: FavoritesPage,
});

function FavoritesPage() {
  const activeIds = useActiveMarketIds();
  const { productFavorites, toggleProductFavorite, addToBasket } = useStore();
  const favorites = PRODUCTS.filter((p) => productFavorites.includes(p.id));
  const offers = currentOffers(activeIds);

  return (
    <div>
      <PageHeader title="Favoriten" subtitle={`${favorites.length} Lieblingsartikel`} />
      <section className="space-y-3 px-5">
        {favorites.map((product) => {
          const best = offers
            .filter((o) => o.product.id === product.id)
            .sort((a, b) => a.price.offer!.price - b.price.offer!.price)[0];
          return (
            <article key={product.id} className="surface-card flex items-center gap-3 p-3">
              <div className="flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-2xl bg-surface-2 text-2xl">
                {(product as any).imageUrl ? <img src={(product as any).imageUrl} alt={product.name} className="h-full w-full object-cover" /> : product.emoji}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{product.name}</p>
                <p className="truncate text-xs text-muted-foreground">{product.brand}{product.unit ? ` · ${product.unit}` : ""}</p>
                {best ? (
                  <p className="mt-1 text-xs text-muted-foreground">{best.market.name} · <span className="font-semibold text-deal">{formatEuro(best.price.offer!.price)}</span></p>
                ) : (
                  <p className="mt-1 text-xs text-muted-foreground">Aktuell kein Angebot in deinen Märkten</p>
                )}
              </div>
              <div className="flex items-center gap-2">
                <button onClick={() => toggleProductFavorite(product.id)} className="rounded-full p-2 text-deal" aria-label="Favorit entfernen"><Heart className="h-5 w-5 fill-current" /></button>
                <button onClick={() => { addToBasket(product.id); toast.success(`${product.name} auf der Liste`); }} className="rounded-full bg-primary p-2.5 text-primary-foreground" aria-label="Zur Liste"><Plus className="h-4 w-4" /></button>
              </div>
            </article>
          );
        })}
        {favorites.length === 0 && (
          <div className="surface-card p-7 text-center text-sm text-muted-foreground">Noch keine Favoriten. In Angeboten kannst du Artikel mit dem Herz markieren.</div>
        )}
      </section>
    </div>
  );
}

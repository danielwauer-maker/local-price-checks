import { createFileRoute } from "@tanstack/react-router";
import { Heart, ShoppingBasket, Shuffle } from "lucide-react";
import { PageHeader } from "@/components/AppShell";
import { PRODUCTS } from "@/data/demo";
import { useStore } from "@/lib/app-store";
import { hasAlternativeFamily } from "@/lib/favorite-matching";
import { useFavoriteAlternatives } from "@/lib/use-favorite-alternatives";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

export const Route = createFileRoute("/favoriten")({ component: FavoritesPage });

function FavoritesPage() {
  const { productFavorites, toggleProductFavorite, basket, toggleBasket } = useStore();
  const { preferences, setEnabled, removePreference } = useFavoriteAlternatives();
  const favorites = PRODUCTS.filter((p) => productFavorites.includes(p.id));

  return (
    <div>
      <PageHeader title="Favoriten" subtitle={`${favorites.length} Lieblingsartikel`} />
      <section className="space-y-3 px-5">
        {favorites.map((product) => {
          const inBasket = (basket[product.id] ?? 0) > 0;
          const alternativesAvailable = hasAlternativeFamily(product);
          const alternativesEnabled = alternativesAvailable && Boolean(preferences[product.id]);
          return (
            <article key={product.id} className="surface-card flex items-center gap-3 p-3">
              <div className="flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-2xl bg-surface-2 text-2xl">
                {(product as any).imageUrl ? <img src={(product as any).imageUrl} alt={product.name} className="h-full w-full object-cover" /> : product.emoji}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{product.name}</p>
              </div>
              <div className="flex items-center gap-1.5">
                <button
                  onClick={() => alternativesAvailable && setEnabled(product.id, !alternativesEnabled)}
                  disabled={!alternativesAvailable}
                  className={cn(
                    "rounded-full p-2.5 transition-colors",
                    alternativesEnabled ? "bg-primary-soft text-primary" : "bg-secondary text-muted-foreground",
                    !alternativesAvailable && "cursor-not-allowed opacity-35",
                  )}
                  aria-pressed={alternativesEnabled}
                  aria-label={alternativesEnabled ? "Alternativen deaktivieren" : "Alternativen zulassen"}
                  title={alternativesAvailable ? (alternativesEnabled ? "Nur dieses Produkt empfehlen" : "Auch passende Alternativen empfehlen") : "Für diesen Artikel ist noch keine Alternativgruppe hinterlegt"}
                >
                  <Shuffle className="h-5 w-5" />
                </button>
                <button
                  onClick={() => {
                    removePreference(product.id);
                    toggleProductFavorite(product.id);
                  }}
                  className="rounded-full p-2 text-deal"
                  aria-label="Favorit entfernen"
                ><Heart className="h-5 w-5 fill-current" /></button>
                <button
                  onClick={() => { toggleBasket(product.id); toast.success(inBasket ? `${product.name} von der Liste entfernt` : `${product.name} auf der Liste`); }}
                  className={cn("rounded-full p-2.5 transition-colors", inBasket ? "bg-primary-soft text-primary" : "bg-secondary text-muted-foreground")}
                  aria-label={inBasket ? "Von Einkaufsliste entfernen" : "Zur Einkaufsliste hinzufügen"}
                ><ShoppingBasket className={cn("h-5 w-5", inBasket && "fill-current/15")} /></button>
              </div>
            </article>
          );
        })}
        {favorites.length === 0 && <div className="surface-card p-7 text-center text-sm text-muted-foreground">Noch keine Favoriten. In Angeboten kannst du Artikel mit dem Herz markieren.</div>}
      </section>
    </div>
  );
}

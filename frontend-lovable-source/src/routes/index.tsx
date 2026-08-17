import { createFileRoute, Link } from "@tanstack/react-router";
import { useMemo } from "react";
import { MapPin, Settings } from "lucide-react";
import { useActiveMarketIds, useStore } from "@/lib/app-store";
import { currentOffers, formatEuro } from "@/data/demo";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "LocalPrices – Supermärkte vergleichen & clever sparen" },
      { name: "description", content: "Vergleiche Supermärkte in deinem Umkreis, finde die besten Angebote und erhalte automatisch die optimale Einkaufsliste mit maximaler Ersparnis." },
    ],
  }),
  component: Index,
});

function Index() {
  const { location, productFavorites, profile } = useStore();
  const activeIds = useActiveMarketIds();

  const favoriteOffers = useMemo(
    () => currentOffers(activeIds).filter((o) => productFavorites.includes(o.product.id)),
    [activeIds, productFavorites],
  );
  const topOffers = favoriteOffers.slice(0, 4);
  const favoriteHeadline = favoriteOffers.length === 1
    ? "1 Favorit ist aktuell besonders günstig"
    : `${favoriteOffers.length} Favoriten sind aktuell besonders günstig`;

  return (
    <div>
      <section className="gradient-hero relative rounded-b-[2rem] px-5 pb-7 pt-[max(1.5rem,env(safe-area-inset-top))] text-primary-foreground">
        <Link
          to="/settings"
          className="absolute right-5 top-[max(1.25rem,env(safe-area-inset-top))] flex h-10 w-10 items-center justify-center rounded-full bg-white/15 transition-colors hover:bg-white/20"
          aria-label="Einstellungen"
        >
          <Settings className="h-5 w-5" />
        </Link>

        <div className="pr-14">
          <p className="text-xs font-medium uppercase tracking-[0.18em] opacity-75">LocalPrices</p>
          <h1 className="mt-1 text-2xl font-semibold">{profile.displayName ? `Hallo, ${profile.displayName}` : "Clever einkaufen"}</h1>
          <Link to="/settings" className="mt-1 flex items-center gap-1 text-sm opacity-85 hover:opacity-100">
            <MapPin className="h-3.5 w-3.5" /> {location.label}
          </Link>
        </div>
      </section>

      <section className="px-5 pt-6">
        <div className="flex items-baseline justify-between">
          <h2 className="text-base font-semibold">{favoriteHeadline}</h2>
          <Link to="/favoriten" className="text-xs font-semibold text-primary">Favoriten</Link>
        </div>
        <div className="mt-3 space-y-3">
          {topOffers.map((o) => (
            <article key={`${o.product.id}-${o.market.id}`} className="surface-card flex items-center gap-3 p-3">
              <span className="flex h-12 w-12 items-center justify-center overflow-hidden rounded-2xl bg-surface-2 text-2xl">
                {(o.product as any).imageUrl ? <img src={(o.product as any).imageUrl} alt={o.product.name} className="h-full w-full object-cover" /> : o.product.emoji}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{o.product.name}</p>
                <p className="truncate text-[11px] text-muted-foreground">{o.market.name} · bis {o.price.offer!.until}</p>
              </div>
              <div className="text-right"><p className="tabular text-base font-bold text-deal">{formatEuro(o.price.offer!.price)}</p></div>
            </article>
          ))}
          {productFavorites.length === 0 && (
            <p className="surface-card p-5 text-center text-sm text-muted-foreground">Markiere Lieblingsartikel als Favoriten – dann erscheinen ihre Angebote hier.</p>
          )}
          {productFavorites.length > 0 && activeIds.length > 0 && favoriteOffers.length === 0 && (
            <p className="surface-card p-5 text-center text-sm text-muted-foreground">Für deine Favoriten gibt es aktuell keine Angebote in den ausgewählten Märkten.</p>
          )}
        </div>
      </section>
    </div>
  );
}

import { createFileRoute, Link } from "@tanstack/react-router";
import { useMemo } from "react";
import { ArrowRight, Heart, MapPin, Settings, Sparkles, Tag } from "lucide-react";
import { useActiveMarketIds, useStore } from "@/lib/app-store";
import { useBackendPlan } from "@/lib/use-backend-plan";
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
  const { location, basketEntries, marketsInRadius, productFavorites, profile, maxStops } = useStore();
  const activeIds = useActiveMarketIds();
  const { plan } = useBackendPlan(maxStops);
  const topOffers = useMemo(
    () => currentOffers(activeIds).filter((o) => productFavorites.includes(o.product.id)).slice(0, 4),
    [activeIds, productFavorites],
  );

  return (
    <div>
      <section className="gradient-hero rounded-b-[2rem] px-5 pb-8 pt-[max(1.5rem,env(safe-area-inset-top))] text-primary-foreground">
        <div className="flex items-start justify-between pr-10">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.18em] opacity-75">LocalPrices</p>
            <h1 className="mt-1 text-2xl font-semibold">{profile.displayName ? `Hallo, ${profile.displayName}` : "Clever einkaufen"}</h1>
            <Link to="/settings" className="mt-1 flex items-center gap-1 text-sm opacity-85 hover:opacity-100"><MapPin className="h-3.5 w-3.5" /> {location.label}</Link>
          </div>
          <Link to="/settings" className="flex h-10 w-10 items-center justify-center rounded-full bg-white/15" aria-label="Einstellungen"><Settings className="h-5 w-5" /></Link>
        </div>

        <div className="mt-6 grid grid-cols-3 gap-2 text-center">
          {[
            { value: plan.singleMarket ? formatEuro(Math.max(0, plan.savingsVsSingle)) : "–", label: "mögliche Ersparnis" },
            { value: String(marketsInRadius.length), label: "Märkte im Umkreis" },
            { value: String(productFavorites.length), label: "Favoriten" },
          ].map((s) => (
            <div key={s.label} className="rounded-2xl bg-white/12 px-2 py-3">
              <p className="tabular text-lg font-bold">{s.value}</p>
              <p className="mt-0.5 text-[10px] leading-tight opacity-80">{s.label}</p>
            </div>
          ))}
        </div>
      </section>

      <div className="grid grid-cols-3 gap-3 px-5 pt-5">
        {[
          { to: "/maerkte", icon: MapPin, label: "Karte" },
          { to: "/favoriten", icon: Heart, label: "Favoriten" },
          { to: "/angebote", icon: Tag, label: "Angebote" },
        ].map(({ to, icon: Icon, label }) => (
          <Link key={to} to={to} className="surface-card flex flex-col items-center gap-2 py-4 text-xs font-semibold"><Icon className="h-5 w-5 text-primary" strokeWidth={2.2} />{label}</Link>
        ))}
      </div>

      <section className="px-5 pt-6">
        <Link to="/liste" className="surface-card block p-5">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-primary"><Sparkles className="h-4 w-4" /> Deine optimale Liste</div>
          <div className="mt-2 flex items-end justify-between">
            <div>
              <p className="tabular text-3xl font-bold">{formatEuro(plan.total)}</p>
              <p className="mt-1 text-xs text-muted-foreground">{basketEntries.length} Artikel · {plan.stops.length} {plan.stops.length === 1 ? "Markt" : "Märkte"}</p>
            </div>
            <span className="flex items-center gap-1 rounded-full bg-primary-soft px-3 py-1.5 text-xs font-semibold text-primary">
              {plan.singleMarket ? `${formatEuro(Math.max(0, plan.savingsVsSingle))} gespart` : "Plan öffnen"} <ArrowRight className="h-3.5 w-3.5" />
            </span>
          </div>
        </Link>
      </section>

      <section className="px-5 pt-6">
        <div className="flex items-baseline justify-between"><h2 className="text-base font-semibold">Jetzt besonders günstig</h2><Link to="/favoriten" className="text-xs font-semibold text-primary">Favoriten</Link></div>
        <div className="mt-3 space-y-3">
          {topOffers.map((o) => (
            <article key={`${o.product.id}-${o.market.id}`} className="surface-card flex items-center gap-3 p-3">
              <span className="flex h-12 w-12 items-center justify-center overflow-hidden rounded-2xl bg-surface-2 text-2xl">{(o.product as any).imageUrl ? <img src={(o.product as any).imageUrl} alt={o.product.name} className="h-full w-full object-cover" /> : o.product.emoji}</span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{o.product.name}</p>
                <p className="truncate text-[11px] text-muted-foreground">{o.market.name} · bis {o.price.offer!.until}</p>
              </div>
              <div className="text-right"><p className="tabular text-base font-bold text-deal">{formatEuro(o.price.offer!.price)}</p></div>
            </article>
          ))}
          {productFavorites.length === 0 && <p className="surface-card p-5 text-center text-sm text-muted-foreground">Markiere Lieblingsartikel als Favoriten – dann erscheinen ihre Angebote hier.</p>}
          {productFavorites.length > 0 && activeIds.length > 0 && topOffers.length === 0 && <p className="surface-card p-5 text-center text-sm text-muted-foreground">Für deine Favoriten gibt es aktuell keine Angebote in den ausgewählten Märkten.</p>}
        </div>
      </section>
    </div>
  );
}

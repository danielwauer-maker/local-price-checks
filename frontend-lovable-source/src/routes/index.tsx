import { createFileRoute, Link } from "@tanstack/react-router";
import { useMemo } from "react";
import { ArrowRight, MapPin, ScanLine, Sparkles, Tag, UserRound } from "lucide-react";
import { useActiveMarketIds, useStore } from "@/lib/app-store";
import { useAuth } from "@/lib/use-auth";
import { buildPlan } from "@/lib/optimizer";
import { currentOffers, formatEuro } from "@/data/demo";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "LocalPrices – Supermärkte vergleichen & clever sparen" },
      {
        name: "description",
        content:
          "Vergleiche Supermärkte in deinem Umkreis, finde die besten Angebote und erhalte automatisch die optimale Einkaufsliste mit maximaler Ersparnis.",
      },
      { property: "og:title", content: "LocalPrices – Supermärkte vergleichen & clever sparen" },
      {
        property: "og:description",
        content:
          "Karte mit Märkten im Umkreis, aktuelle Angebote und die automatisch optimierte Einkaufsliste.",
      },
    ],
  }),
  component: Index,
});

function Index() {
  const { location, basketEntries, marketsInRadius, favorites, maxStops } = useStore();
  const activeIds = useActiveMarketIds();
  const { user } = useAuth();

  const plan = useMemo(
    () => buildPlan(basketEntries, activeIds, maxStops),
    [basketEntries, activeIds, maxStops],
  );
  const topOffers = useMemo(() => currentOffers(activeIds).slice(0, 4), [activeIds]);

  return (
    <div>
      <section className="gradient-hero rounded-b-[2rem] px-5 pb-8 pt-[max(1.5rem,env(safe-area-inset-top))] text-primary-foreground">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.18em] opacity-75">
              LocalPrices
            </p>
            <h1 className="mt-1 text-2xl font-semibold">
              {user ? `Hallo, ${user.email?.split("@")[0]}` : "Clever einkaufen"}
            </h1>
            <p className="mt-1 flex items-center gap-1 text-sm opacity-85">
              <MapPin className="h-3.5 w-3.5" /> {location.label}
            </p>
          </div>
          <Link
            to="/auth"
            className="flex h-10 w-10 items-center justify-center rounded-full bg-white/15"
            aria-label="Konto"
          >
            <UserRound className="h-5 w-5" />
          </Link>
        </div>

        <div className="mt-6 grid grid-cols-3 gap-2 text-center">
          {[
            { value: formatEuro(plan.savingsVsWorst), label: "mögliche Ersparnis" },
            { value: String(marketsInRadius.length), label: "Märkte im Umkreis" },
            { value: String(favorites.length), label: "Favoriten" },
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
          { to: "/scanner", icon: ScanLine, label: "Scannen" },
          { to: "/angebote", icon: Tag, label: "Angebote" },
        ].map(({ to, icon: Icon, label }) => (
          <Link
            key={to}
            to={to}
            className="surface-card flex flex-col items-center gap-2 py-4 text-xs font-semibold"
          >
            <Icon className="h-5 w-5 text-primary" strokeWidth={2.2} />
            {label}
          </Link>
        ))}
      </div>

      <section className="px-5 pt-6">
        <Link to="/liste" className="surface-card block p-5">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-primary">
            <Sparkles className="h-4 w-4" /> Deine optimale Liste
          </div>
          <div className="mt-2 flex items-end justify-between">
            <div>
              <p className="tabular text-3xl font-bold">{formatEuro(plan.total)}</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {basketEntries.length} Artikel · {plan.stops.length}{" "}
                {plan.stops.length === 1 ? "Markt" : "Märkte"}
              </p>
            </div>
            <span className="flex items-center gap-1 rounded-full bg-primary-soft px-3 py-1.5 text-xs font-semibold text-primary">
              {formatEuro(plan.savingsVsSingle)} gespart <ArrowRight className="h-3.5 w-3.5" />
            </span>
          </div>
        </Link>
      </section>

      <section className="px-5 pt-6">
        <div className="flex items-baseline justify-between">
          <h2 className="text-base font-semibold">Jetzt besonders günstig</h2>
          <Link to="/angebote" className="text-xs font-semibold text-primary">
            alle
          </Link>
        </div>
        <div className="mt-3 space-y-3">
          {topOffers.map((o) => (
            <article
              key={`${o.product.id}-${o.market.id}`}
              className="surface-card flex items-center gap-3 p-3"
            >
              <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-surface-2 text-2xl">
                {o.product.emoji}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{o.product.name}</p>
                <p className="truncate text-[11px] text-muted-foreground">
                  {o.market.name} · bis {o.price.offer!.until}
                </p>
              </div>
              <div className="text-right">
                <p className="tabular text-base font-bold text-deal">
                  {formatEuro(o.price.offer!.price)}
                </p>
                <p className="text-[10px] font-semibold text-muted-foreground">−{o.discount}%</p>
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

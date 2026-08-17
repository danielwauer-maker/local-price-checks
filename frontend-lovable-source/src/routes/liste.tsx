import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { Minus, Plus, Search, Sparkles, Trash2, TrendingDown } from "lucide-react";
import { PageHeader } from "@/components/AppShell";
import { useActiveMarketIds, useStore } from "@/lib/app-store";
import { PRODUCTS, formatEuro, getProduct } from "@/data/demo";
import { buildPlan } from "@/lib/optimizer";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/liste")({
  head: () => ({
    meta: [
      { title: "Optimale Einkaufsliste & Marktvergleich – LocalPrices" },
      {
        name: "description",
        content:
          "Deine Einkaufsliste automatisch auf die günstigsten Märkte verteilt – mit Ersparnis gegenüber dem Einkauf in nur einem Markt.",
      },
      { property: "og:title", content: "Optimale Einkaufsliste – LocalPrices" },
      {
        property: "og:description",
        content: "Warenkorb intelligent auf Märkte verteilen und maximal sparen.",
      },
    ],
  }),
  component: ListPage,
});

function ListPage() {
  const { basketEntries, setQty, addToBasket, clearBasket, maxStops, setMaxStops } = useStore();
  const activeIds = useActiveMarketIds();
  const [query, setQuery] = useState("");

  const plan = useMemo(
    () => buildPlan(basketEntries, activeIds, maxStops),
    [basketEntries, activeIds, maxStops],
  );

  const suggestions = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return PRODUCTS.filter(
      (p) => p.name.toLowerCase().includes(q) || p.brand.toLowerCase().includes(q),
    ).slice(0, 6);
  }, [query]);

  return (
    <div>
      <PageHeader
        title="Einkaufsliste"
        subtitle={`${basketEntries.length} Artikel · ${activeIds.length} Märkte im Vergleich`}
        action={
          basketEntries.length > 0 ? (
            <button
              onClick={clearBasket}
              className="mt-1 flex items-center gap-1 rounded-full bg-secondary px-3 py-1.5 text-xs font-semibold text-secondary-foreground"
            >
              <Trash2 className="h-3.5 w-3.5" /> leeren
            </button>
          ) : undefined
        }
      />

      <div className="px-5">
        <div className="flex items-center gap-2 rounded-2xl bg-surface px-4 py-3 shadow-card">
          <Search className="h-4 w-4 text-muted-foreground" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Artikel hinzufügen…"
            className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
        </div>
        {suggestions.length > 0 && (
          <ul className="mt-2 overflow-hidden rounded-2xl bg-surface shadow-card">
            {suggestions.map((p) => (
              <li key={p.id}>
                <button
                  onClick={() => {
                    addToBasket(p.id);
                    setQuery("");
                  }}
                  className="flex w-full items-center gap-3 border-b border-border px-4 py-2.5 text-left last:border-0"
                >
                  <span className="text-xl">{p.emoji}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{p.name}</span>
                    <span className="block text-xs text-muted-foreground">
                      {p.brand} · {p.unit}
                    </span>
                  </span>
                  <Plus className="h-4 w-4 text-primary" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {basketEntries.length === 0 ? (
        <p className="mx-5 mt-6 surface-card p-8 text-center text-sm text-muted-foreground">
          Deine Liste ist leer. Füge Artikel hinzu oder übernimm Angebote.
        </p>
      ) : (
        <>
          {/* Ersparnis-Karte */}
          <section className="mx-5 mt-5 overflow-hidden rounded-3xl gradient-hero p-5 text-primary-foreground shadow-float">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide opacity-80">
              <Sparkles className="h-4 w-4" /> Optimaler Plan
            </div>
            <p className="tabular mt-2 text-4xl font-bold">{formatEuro(plan.total)}</p>
            <p className="mt-1 text-sm opacity-85">
              in {plan.stops.length} {plan.stops.length === 1 ? "Markt" : "Märkten"} statt{" "}
              {formatEuro(plan.singleMarketTotal)} bei {plan.singleMarket?.chain}
            </p>
            <div className="mt-4 grid grid-cols-2 gap-2 text-sm">
              <div className="rounded-2xl bg-white/12 px-3 py-2">
                <span className="block text-[11px] opacity-80">ggü. bestem Einzelmarkt</span>
                <span className="tabular font-bold">{formatEuro(plan.savingsVsSingle)}</span>
              </div>
              <div className="rounded-2xl bg-white/12 px-3 py-2">
                <span className="block text-[11px] opacity-80">ggü. teuerstem Markt</span>
                <span className="tabular font-bold">{formatEuro(plan.savingsVsWorst)}</span>
              </div>
            </div>
          </section>

          <div className="mx-5 mt-4 flex items-center justify-between rounded-2xl bg-surface p-3 shadow-card">
            <span className="text-sm font-medium">Max. Anzahl Märkte</span>
            <div className="flex gap-1">
              {[1, 2, 3].map((n) => (
                <button
                  key={n}
                  onClick={() => setMaxStops(n)}
                  className={cn(
                    "h-8 w-9 rounded-xl text-sm font-semibold transition-colors",
                    maxStops === n
                      ? "bg-primary text-primary-foreground"
                      : "bg-secondary text-secondary-foreground",
                  )}
                >
                  {n}
                </button>
              ))}
            </div>
          </div>

          {/* Plan pro Markt */}
          <section className="mt-5 space-y-4 px-5">
            {plan.stops.map((stop, i) => (
              <article key={stop.market.id} className="surface-card overflow-hidden">
                <header className="flex items-center gap-3 border-b border-border px-4 py-3">
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary text-xs font-bold text-primary-foreground">
                    {i + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold">{stop.market.name}</p>
                    <p className="text-[11px] text-muted-foreground">
                      {stop.market.city} · bis {stop.market.openUntil} Uhr
                    </p>
                  </div>
                  <span className="tabular text-sm font-bold">{formatEuro(stop.total)}</span>
                </header>
                <ul>
                  {stop.lines.map((line) => (
                    <li
                      key={line.product.id}
                      className="flex items-center gap-3 border-b border-border px-4 py-2.5 last:border-0"
                    >
                      <span className="text-xl">{line.product.emoji}</span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">{line.product.name}</p>
                        <p className="text-[11px] text-muted-foreground">
                          {line.product.unit}
                          {line.isOffer && (
                            <span className="ml-1.5 rounded-full bg-deal/12 px-1.5 py-0.5 font-semibold text-deal">
                              Angebot
                            </span>
                          )}
                          {line.saved > 0 && (
                            <span className="ml-1.5 inline-flex items-center gap-0.5 text-primary">
                              <TrendingDown className="h-3 w-3" />
                              {formatEuro(line.saved)}
                            </span>
                          )}
                        </p>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <button
                          onClick={() => setQty(line.product.id, line.qty - 1)}
                          className="flex h-7 w-7 items-center justify-center rounded-full bg-secondary text-secondary-foreground"
                          aria-label="weniger"
                        >
                          <Minus className="h-3.5 w-3.5" />
                        </button>
                        <span className="tabular w-4 text-center text-sm font-semibold">
                          {line.qty}
                        </span>
                        <button
                          onClick={() => setQty(line.product.id, line.qty + 1)}
                          className="flex h-7 w-7 items-center justify-center rounded-full bg-secondary text-secondary-foreground"
                          aria-label="mehr"
                        >
                          <Plus className="h-3.5 w-3.5" />
                        </button>
                      </div>
                      <span className="tabular w-14 text-right text-sm font-semibold">
                        {formatEuro(line.lineTotal)}
                      </span>
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </section>

          <p className="px-5 pt-4 text-center text-[11px] text-muted-foreground">
            Preise sind Demodaten und dienen dem Vergleich.{" "}
            {getProduct(basketEntries[0]!.productId)?.name} u. a. laut letzter Prospektauswertung.
          </p>
        </>
      )}
    </div>
  );
}

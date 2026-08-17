import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { Plus, Search } from "lucide-react";
import { PageHeader } from "@/components/AppShell";
import { useActiveMarketIds, useStore } from "@/lib/app-store";
import { CATEGORIES, currentOffers, formatEuro, type Category } from "@/data/demo";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

export const Route = createFileRoute("/angebote")({
  head: () => ({
    meta: [
      { title: "Aktuelle Angebote deiner Märkte – LocalPrices" },
      {
        name: "description",
        content:
          "Alle laufenden Angebote deiner ausgewählten Supermärkte nach Rabatt sortiert – direkt auf die Einkaufsliste setzen.",
      },
      { property: "og:title", content: "Aktuelle Angebote – LocalPrices" },
      {
        property: "og:description",
        content: "Angebote deiner Märkte nach Rabatt sortiert und filterbar.",
      },
    ],
  }),
  component: OffersPage,
});

function OffersPage() {
  const activeIds = useActiveMarketIds();
  const { addToBasket } = useStore();
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<Category | "Alle">("Alle");

  const offers = useMemo(() => {
    const q = query.trim().toLowerCase();
    return currentOffers(activeIds).filter(
      (o) =>
        (category === "Alle" || o.product.category === category) &&
        (q === "" ||
          o.product.name.toLowerCase().includes(q) ||
          o.product.brand.toLowerCase().includes(q)),
    );
  }, [activeIds, query, category]);

  return (
    <div>
      <PageHeader
        title="Angebote"
        subtitle={`${offers.length} Aktionen in ${activeIds.length} Märkten`}
      />

      <div className="px-5">
        <div className="flex items-center gap-2 rounded-2xl bg-surface px-4 py-3 shadow-card">
          <Search className="h-4 w-4 text-muted-foreground" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Produkt oder Marke suchen"
            className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
        </div>
      </div>

      <div className="no-scrollbar mt-4 flex gap-2 overflow-x-auto px-5 pb-1">
        {(["Alle", ...CATEGORIES] as const).map((c) => (
          <button
            key={c}
            onClick={() => setCategory(c)}
            className={cn(
              "shrink-0 rounded-full px-3.5 py-1.5 text-xs font-semibold transition-colors",
              category === c
                ? "bg-primary text-primary-foreground"
                : "bg-surface text-muted-foreground shadow-card",
            )}
          >
            {c}
          </button>
        ))}
      </div>

      <section className="mt-4 space-y-3 px-5">
        {offers.map((o) => (
          <article key={`${o.product.id}-${o.market.id}`} className="surface-card flex gap-3 p-3">
            <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-surface-2 text-3xl">
              {o.product.emoji}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold">{o.product.name}</p>
              <p className="text-xs text-muted-foreground">
                {o.product.brand} · {o.product.unit}
              </p>
              <p className="mt-1 text-[11px] text-muted-foreground">
                {o.market.name} · bis {o.price.offer!.until}
              </p>
              <div className="mt-1.5 flex items-baseline gap-2">
                <span className="tabular text-lg font-bold text-deal">
                  {formatEuro(o.price.offer!.price)}
                </span>
                <span className="tabular text-xs text-muted-foreground line-through">
                  {formatEuro(o.price.price)}
                </span>
                <span className="rounded-full gradient-deal px-2 py-0.5 text-[10px] font-bold text-deal-foreground">
                  −{o.discount}%
                </span>
              </div>
            </div>
            <button
              onClick={() => {
                addToBasket(o.product.id);
                toast.success(`${o.product.name} auf der Liste`);
              }}
              className="self-center rounded-full bg-primary p-2.5 text-primary-foreground shadow-float"
              aria-label="Zur Einkaufsliste"
            >
              <Plus className="h-4 w-4" strokeWidth={2.6} />
            </button>
          </article>
        ))}

        {offers.length === 0 && (
          <p className="surface-card p-6 text-center text-sm text-muted-foreground">
            Keine Angebote für diese Auswahl.
          </p>
        )}
      </section>
    </div>
  );
}

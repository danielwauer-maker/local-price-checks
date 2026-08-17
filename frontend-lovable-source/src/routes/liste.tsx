import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { Check, Minus, Plus, Search, Trash2 } from "lucide-react";
import { PageHeader } from "@/components/AppShell";
import { useActiveMarketIds, useStore } from "@/lib/app-store";
import { PRODUCTS, currentOffers, formatEuro } from "@/data/demo";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/liste")({
  head: () => ({ meta: [{ title: "Einkaufsliste & Angebotsvergleich – LocalPrices" }] }),
  component: ListPage,
});

function ListPage() {
  const { basketEntries, setQty, addToBasket, clearBasket, checked, toggleChecked } = useStore();
  const activeIds = useActiveMarketIds();
  const [query, setQuery] = useState("");

  const basketByProduct = useMemo(
    () => new Map(basketEntries.map((entry) => [entry.productId, entry.qty])),
    [basketEntries],
  );

  const basketProductIds = useMemo(() => new Set(basketEntries.map((entry) => entry.productId)), [basketEntries]);

  const suggestions = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return PRODUCTS.filter((p) => p.name.toLowerCase().includes(q) || p.brand.toLowerCase().includes(q)).slice(0, 6);
  }, [query]);

  const marketGroups = useMemo(() => {
    const bestPerProductMarket = new Map<string, ReturnType<typeof currentOffers>[number]>();
    for (const offer of currentOffers(activeIds)) {
      if (!basketProductIds.has(offer.product.id)) continue;
      const key = `${offer.market.id}:${offer.product.id}`;
      const existing = bestPerProductMarket.get(key);
      if (!existing || offer.price.offer!.price < existing.price.offer!.price) {
        bestPerProductMarket.set(key, offer);
      }
    }

    const grouped = new Map<string, { market: ReturnType<typeof currentOffers>[number]["market"]; rows: ReturnType<typeof currentOffers> }>();
    for (const offer of bestPerProductMarket.values()) {
      const existing = grouped.get(offer.market.id);
      if (existing) existing.rows.push(offer);
      else grouped.set(offer.market.id, { market: offer.market, rows: [offer] });
    }

    return [...grouped.values()]
      .map((group) => ({
        ...group,
        rows: group.rows.sort((a, b) => a.product.name.localeCompare(b.product.name, "de")),
      }))
      .sort((a, b) => a.market.name.localeCompare(b.market.name, "de"));
  }, [activeIds, basketProductIds]);

  const productsWithOffer = useMemo(() => {
    const ids = new Set<string>();
    for (const group of marketGroups) for (const offer of group.rows) ids.add(offer.product.id);
    return ids;
  }, [marketGroups]);

  const missing = useMemo(
    () => basketEntries
      .filter((entry) => !productsWithOffer.has(entry.productId))
      .map((entry) => ({ product: PRODUCTS.find((p) => p.id === entry.productId)!, qty: entry.qty }))
      .filter((row) => Boolean(row.product)),
    [basketEntries, productsWithOffer],
  );

  const CheckButton = ({ id }: { id: string }) => {
    const done = checked.includes(id);
    return (
      <button
        onClick={() => toggleChecked(id)}
        aria-label={done ? "Als nicht gekauft markieren" : "Als gekauft markieren"}
        className={cn(
          "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2",
          done ? "border-primary bg-primary text-primary-foreground" : "border-border bg-surface",
        )}
      >
        {done && <Check className="h-3.5 w-3.5" />}
      </button>
    );
  };

  return (
    <div>
      <PageHeader
        title="Einkaufsliste"
        subtitle={`${basketEntries.length} Artikel · ${activeIds.length} Märkte im Vergleich`}
        action={basketEntries.length > 0 ? (
          <button onClick={clearBasket} className="mt-1 flex items-center gap-1 rounded-full bg-secondary px-3 py-1.5 text-xs font-semibold text-secondary-foreground">
            <Trash2 className="h-3.5 w-3.5" /> leeren
          </button>
        ) : undefined}
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
                  onClick={() => { addToBasket(p.id); setQuery(""); }}
                  className="flex w-full items-center gap-3 border-b border-border px-4 py-2.5 text-left last:border-0"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium">{p.name}</span>
                    <span className="block text-xs text-muted-foreground">{p.brand}{p.unit ? ` · ${p.unit}` : ""}</span>
                  </span>
                  <Plus className="h-4 w-4 text-primary" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {basketEntries.length === 0 ? (
        <p className="mx-5 mt-6 surface-card p-8 text-center text-sm text-muted-foreground">Deine Liste ist leer. Füge Artikel hinzu oder übernimm Angebote.</p>
      ) : (
        <>
          <section className="mt-5 space-y-4 px-5">
            {activeIds.length === 0 && (
              <div className="surface-card p-5 text-center text-sm text-muted-foreground">
                Wähle unter „Märkte“ mindestens einen Markt aus, um Angebote für deine Einkaufsliste zu vergleichen.
              </div>
            )}

            {marketGroups.map((group) => {
              const logoUrl = (group.market as any).logoUrl as string | undefined;
              const subtotal = group.rows.reduce((sum, offer) => sum + offer.price.offer!.price * (basketByProduct.get(offer.product.id) ?? 1), 0);
              return (
                <article key={group.market.id} className="surface-card overflow-hidden">
                  <header className="flex items-center gap-3 border-b border-border px-4 py-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-surface-2">
                      {logoUrl ? <img src={logoUrl} alt={group.market.chain} className="h-full w-full object-contain p-1" /> : <span className="text-[10px] font-bold text-primary">{group.market.chain.slice(0, 4)}</span>}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-semibold">{group.market.name}</p>
                      <p className="text-[11px] text-muted-foreground">{group.rows.length} {group.rows.length === 1 ? "Artikel" : "Artikel"} aus deiner Liste im Angebot</p>
                    </div>
                    <span className="tabular shrink-0 text-sm font-bold">{formatEuro(subtotal)}</span>
                  </header>

                  <ul>
                    {group.rows.map((offer) => {
                      const qty = basketByProduct.get(offer.product.id) ?? 1;
                      const done = checked.includes(offer.product.id);
                      const lineTotal = offer.price.offer!.price * qty;
                      return (
                        <li
                          key={`${group.market.id}-${offer.product.id}`}
                          className={cn("flex items-center gap-3 border-b border-border px-4 py-3 last:border-0", done && "bg-secondary/35 opacity-65")}
                        >
                          <CheckButton id={offer.product.id} />
                          <div className="min-w-0 flex-1">
                            <p className={cn("text-sm font-medium leading-snug", done && "line-through")}>{offer.product.name}</p>
                            <p className="mt-0.5 text-[11px] text-muted-foreground">
                              {offer.product.unit || ""}{offer.product.unit ? " · " : ""}{formatEuro(offer.price.offer!.price)} / Stück
                            </p>
                          </div>
                          <div className="flex shrink-0 items-center gap-1.5">
                            <button onClick={() => setQty(offer.product.id, qty - 1)} className="flex h-7 w-7 items-center justify-center rounded-full bg-secondary"><Minus className="h-3.5 w-3.5" /></button>
                            <span className="tabular w-4 text-center text-sm font-semibold">{qty}</span>
                            <button onClick={() => setQty(offer.product.id, qty + 1)} className="flex h-7 w-7 items-center justify-center rounded-full bg-secondary"><Plus className="h-3.5 w-3.5" /></button>
                          </div>
                          <span className="tabular w-14 shrink-0 text-right text-sm font-semibold">{formatEuro(lineTotal)}</span>
                        </li>
                      );
                    })}
                  </ul>
                </article>
              );
            })}

            {missing.length > 0 && (
              <article className="surface-card overflow-hidden border border-dashed border-border">
                <header className="px-4 py-3 text-sm font-semibold">Aktuell ohne Angebot</header>
                <ul>
                  {missing.map((line) => {
                    const done = checked.includes(line.product.id);
                    return (
                      <li key={line.product.id} className={cn("flex items-center gap-3 border-t border-border px-4 py-3", done && "opacity-55")}>
                        <CheckButton id={line.product.id} />
                        <span className={cn("min-w-0 flex-1 text-sm leading-snug", done && "line-through")}>{line.product.name}</span>
                        <span className="shrink-0 text-xs text-muted-foreground">Menge {line.qty}</span>
                      </li>
                    );
                  })}
                </ul>
              </article>
            )}
          </section>

          <p className="px-5 pt-4 text-center text-[11px] text-muted-foreground">
            Ein Artikel kann bei mehreren Märkten erscheinen, wenn er dort gleichzeitig im Angebot ist. So kannst du die Preise direkt vergleichen.
          </p>
        </>
      )}
    </div>
  );
}

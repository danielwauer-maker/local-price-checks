import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { ChevronDown, Heart, Search, ShoppingBasket } from "lucide-react";
import { PageHeader } from "@/components/AppShell";
import { useActiveMarketIds, useStore } from "@/lib/app-store";
import { currentOffers, formatEuro } from "@/data/demo";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

export const Route = createFileRoute("/angebote")({
  head: () => ({ meta: [{ title: "Aktuelle Angebote deiner Märkte – LocalPrices" }] }),
  component: OffersPage,
});

function OffersPage() {
  const activeIds = useActiveMarketIds();
  const { basket, toggleBasket, productFavorites, toggleProductFavorite } = useStore();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<Record<string, boolean>>({});

  const offers = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (activeIds.length === 0) return [];
    return currentOffers(activeIds).filter(
      (o) => q === "" || o.product.name.toLowerCase().includes(q) || o.product.brand.toLowerCase().includes(q),
    );
  }, [activeIds, query]);

  const groups = useMemo(() => {
    const grouped = new Map<string, typeof offers>();
    for (const offer of offers) {
      const category = String(offer.product.category || "Sonstiges");
      grouped.set(category, [...(grouped.get(category) ?? []), offer]);
    }
    return [...grouped.entries()].sort((a, b) => a[0].localeCompare(b[0], "de"));
  }, [offers]);

  return (
    <div>
      <PageHeader title="Angebote" subtitle={`${offers.length} Aktionen in ${activeIds.length} Märkten`} />

      <div className="px-5">
        <div className="flex items-center gap-2 rounded-2xl bg-surface px-4 py-3 shadow-card">
          <Search className="h-4 w-4 text-muted-foreground" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Produkt oder Marke suchen" className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground" />
        </div>
      </div>

      <section className="mt-4 space-y-3 px-5">
        {groups.map(([category, rows], index) => {
          const expanded = query.trim() !== "" || (open[category] ?? index === 0);
          return (
            <div key={category} className="surface-card overflow-hidden">
              <button onClick={() => setOpen((s) => ({ ...s, [category]: !expanded }))} className="flex w-full items-center gap-3 px-4 py-3.5 text-left">
                <div className="min-w-0 flex-1"><p className="text-sm font-semibold">{category}</p><p className="text-[11px] text-muted-foreground">{rows.length} Artikel</p></div>
                <span className="rounded-full bg-primary-soft px-2.5 py-1 text-xs font-bold text-primary">{rows.length}</span>
                <ChevronDown className={cn("h-4 w-4 text-muted-foreground transition-transform", expanded && "rotate-180")} />
              </button>

              {expanded && (
                <div className="border-t border-border">
                  {rows.map((o) => {
                    const favorite = productFavorites.includes(o.product.id);
                    const inBasket = (basket[o.product.id] ?? 0) > 0;
                    return (
                      <article key={`${o.product.id}-${o.market.id}`} className="flex gap-3 border-b border-border p-3 last:border-0">
                        <div className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-2xl bg-surface-2 text-3xl">
                          {(o.product as any).imageUrl ? <img src={(o.product as any).imageUrl} alt={o.product.name} className="h-full w-full object-cover" /> : o.product.emoji}
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-semibold">{o.product.name}</p>
                          <p className="text-xs text-muted-foreground">{o.product.brand}{o.product.brand && o.product.unit ? " · " : ""}{o.product.unit}</p>
                          <p className="mt-1 text-[11px] text-muted-foreground">{o.market.name} · bis {o.price.offer!.until}</p>
                          <div className="mt-1.5 flex items-baseline gap-2"><span className="tabular text-lg font-bold text-deal">{formatEuro(o.price.offer!.price)}</span></div>
                        </div>
                        <div className="flex flex-col items-center justify-center gap-2">
                          <button onClick={() => toggleProductFavorite(o.product.id)} className={cn("rounded-full p-2", favorite ? "bg-deal/12 text-deal" : "bg-secondary text-muted-foreground")} aria-label="Favorit"><Heart className={cn("h-4 w-4", favorite && "fill-current")} /></button>
                          <button
                            onClick={() => { toggleBasket(o.product.id); toast.success(inBasket ? `${o.product.name} von der Liste entfernt` : `${o.product.name} auf der Liste`); }}
                            className={cn("rounded-full p-2.5 transition-colors", inBasket ? "bg-primary-soft text-primary" : "bg-secondary text-muted-foreground")}
                            aria-label={inBasket ? "Von Einkaufsliste entfernen" : "Zur Einkaufsliste hinzufügen"}
                          ><ShoppingBasket className={cn("h-5 w-5", inBasket && "fill-current/15")} /></button>
                        </div>
                      </article>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}

        {offers.length === 0 && (
          <p className="surface-card p-6 text-center text-sm text-muted-foreground">
            {activeIds.length === 0 ? "Wähle zuerst mindestens einen Markt für den Vergleich aus." : "Keine Angebote für diese Auswahl."}
          </p>
        )}
      </section>
    </div>
  );
}

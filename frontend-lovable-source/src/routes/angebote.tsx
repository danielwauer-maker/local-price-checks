import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { CalendarDays, ChevronDown, Search, Store, Tag } from "lucide-react";
import { PageHeader } from "@/components/AppShell";
import { OfferRow } from "@/components/lokero/OfferCard";
import { EmptyState, ErrorState, SkeletonList } from "@/components/lokero/States";
import { fetchOffers, fetchOfferWeek } from "@/services/lokero-api";
import { fetchCategories } from "@/services/lokero-categories-api";
import type { CategoryId } from "@/data/lokero";
import { formatDateRange } from "@/lib/format";
import { useStore } from "@/lib/app-store";
import { cn } from "@/lib/utils";

type OfferSearch = { category?: CategoryId };

export const Route = createFileRoute("/angebote")({
  validateSearch: (search: Record<string, unknown>): OfferSearch => ({
    ...(search["category"] ? { category: search["category"] as CategoryId } : {}),
  }),
  head: () => ({ meta: [{ title: "Aktuelle Angebote deiner Märkte – Lokero" }] }),
  component: OffersScreen,
});

function OffersScreen() {
  const initial = Route.useSearch();
  const { favoriteMarkets } = useStore();
  const [search, setSearch] = useState("");
  const [openCategories, setOpenCategories] = useState<Set<string>>(
    () => new Set(initial.category ? [initial.category] : []),
  );
  const categories = useQuery({ queryKey: ["lokero-categories"], queryFn: fetchCategories });
  const query = useQuery({
    queryKey: ["offers"],
    queryFn: () => fetchOffers({ categoryId: null, tag: null }),
  });
  const week = useQuery({ queryKey: ["offer-week"], queryFn: fetchOfferWeek });

  const groups = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase("de");
    const rows = (query.data ?? []).filter((offer) => {
      if (!needle) return true;
      const product = offer.product;
      return [product.name, product.brand, product.detail, product.amount]
        .filter(Boolean)
        .some((value) => String(value).toLocaleLowerCase("de").includes(needle));
    });
    const categoryRows = categories.data ?? [];
    return categoryRows
      .map((category) => ({
        category,
        offers: rows.filter((offer) => offer.product.category === category.id),
      }))
      .filter((group) => group.offers.length > 0);
  }, [query.data, categories.data, search]);

  const visibleOfferCount = groups.reduce((sum, group) => sum + group.offers.length, 0);

  const toggleCategory = (categoryId: string) => {
    setOpenCategories((current) => {
      const next = new Set(current);
      if (next.has(categoryId)) next.delete(categoryId);
      else next.add(categoryId);
      return next;
    });
  };

  return (
    <div>
      <PageHeader title="Angebote" />

      <div className="space-y-3 px-4 pt-3">
        {favoriteMarkets.length === 0 && (
          <div className="flex items-start gap-2.5 rounded-xl border border-border bg-surface px-3 py-3">
            <Store className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <p className="text-[12px] leading-relaxed text-muted-foreground">
              Du hast noch keine Märkte ausgewählt – aktuell zeigen wir alle freigegebenen Märkte in deinem Umkreis.
            </p>
          </div>
        )}

        <label className="flex h-11 items-center gap-2 rounded-xl border border-border bg-surface px-3">
          <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="sr-only">Angebote durchsuchen</span>
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Angebote durchsuchen"
            className="min-w-0 flex-1 bg-transparent text-[13px] text-navy outline-none placeholder:text-muted-foreground"
          />
        </label>

        <div className="flex items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2.5">
          <CalendarDays className="h-4 w-4 shrink-0 text-primary" />
          <p className="tabular min-w-0 flex-1 truncate text-[12px] font-medium text-navy">
            {week.data ? `Diese Woche: ${formatDateRange(week.data.from, week.data.until)}` : "Angebotszeitraum wird geladen …"}
          </p>
        </div>
      </div>

      <div className="px-4 pt-3">
        {query.isLoading && <SkeletonList count={5} />}
        {query.isError && <ErrorState onRetry={() => query.refetch()} />}
        {query.isSuccess && visibleOfferCount === 0 && (
          <EmptyState
            icon={Tag}
            title="Keine Angebote gefunden"
            description={search ? "Für deine Suche wurden keine Angebote gefunden." : "Diese Woche wurden keine Angebote gefunden."}
            action={search ? <button onClick={() => setSearch("")} className="inline-flex h-11 items-center rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground">Suche löschen</button> : undefined}
          />
        )}

        <div className="space-y-2.5">
          {groups.map(({ category, offers }) => {
            const open = openCategories.has(category.id);
            return (
              <section key={category.id} className="overflow-hidden rounded-xl border border-border bg-surface">
                <button
                  type="button"
                  onClick={() => toggleCategory(category.id)}
                  aria-expanded={open}
                  className="flex w-full items-center gap-3 px-3 py-3 text-left"
                >
                  <span className="min-w-0 flex-1 text-[13px] font-semibold text-navy">
                    {category.label} <span className="font-normal text-muted-foreground">· {offers.length} Angebote</span>
                  </span>
                  <ChevronDown className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} />
                </button>
                {open && (
                  <div className="space-y-2.5 border-t border-border p-2.5">
                    {offers.map((offer) => <OfferRow key={`${offer.productId}-${offer.marketId}`} offer={offer} />)}
                  </div>
                )}
              </section>
            );
          })}
        </div>
      </div>
    </div>
  );
}

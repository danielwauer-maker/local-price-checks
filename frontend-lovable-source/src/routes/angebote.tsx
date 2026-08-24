import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { CalendarDays, Tag } from "lucide-react";
import { PageHeader } from "@/components/AppShell";
import { FilterChips } from "@/components/lokero/FilterChips";
import { OfferRow } from "@/components/lokero/OfferCard";
import { EmptyState, ErrorState, SkeletonList } from "@/components/lokero/States";
import { fetchOffers, fetchOfferWeek, listCategories } from "@/services/lokero-api";
import type { CategoryId, DietTag } from "@/data/lokero";
import { formatDateRange } from "@/lib/format";

type OfferSearch = { category?: CategoryId; tag?: DietTag };

export const Route = createFileRoute("/angebote")({
  validateSearch: (search: Record<string, unknown>): OfferSearch => ({
    ...(search["category"] ? { category: search["category"] as CategoryId } : {}),
    ...(search["tag"] ? { tag: search["tag"] as DietTag } : {}),
  }),
  head: () => ({
    meta: [
      { title: "Aktuelle Angebote deiner Märkte – Lokero" },
      {
        name: "description",
        content:
          "Alle Wochenangebote deiner lokalen Märkte mit Rabatt, Grundpreis und Prospektseite – filterbar nach Kategorie, vegan und glutenfrei.",
      },
      { property: "og:title", content: "Aktuelle Angebote – Lokero" },
      {
        property: "og:description",
        content: "Wochenangebote lokaler Märkte mit Rabatt und Grundpreis.",
      },
    ],
  }),
  component: OffersScreen,
});

function OffersScreen() {
  const initial = Route.useSearch();
  const [filter, setFilter] = useState<string>(
    initial.category ?? initial.tag ?? "alle",
  );

  const categories = listCategories();
  const options = [
    { id: "alle", label: "Alle Angebote" },
    { id: "vegan", label: "Vegan" },
    { id: "glutenfrei", label: "Glutenfrei" },
    { id: "bio", label: "Bio" },
    ...categories.map((c) => ({ id: c.id, label: c.label })),
  ];

  const isTag = ["vegan", "glutenfrei", "bio", "vegetarisch"].includes(filter);
  const query = useQuery({
    queryKey: ["offers", filter],
    queryFn: () =>
      fetchOffers({
        categoryId: !isTag && filter !== "alle" ? (filter as CategoryId) : null,
        tag: isTag ? (filter as DietTag) : null,
      }),
  });
  const week = useQuery({ queryKey: ["offer-week"], queryFn: fetchOfferWeek });

  return (
    <div>
      <PageHeader title="Angebote" />

      <div className="bg-surface px-4 pb-3">
        <FilterChips options={options} value={filter} onChange={setFilter} />
      </div>

      <div className="px-4 pt-3">
        <div className="flex items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2.5">
          <CalendarDays className="h-4 w-4 shrink-0 text-primary" />
          <p className="tabular min-w-0 flex-1 truncate text-[12px] font-medium text-navy">
            {week.data
              ? `Diese Woche: ${formatDateRange(week.data.from, week.data.until)}`
              : "Angebotszeitraum wird geladen …"}
          </p>
          <button className="shrink-0 text-[12px] font-semibold text-primary">Ändern</button>
        </div>
      </div>

      <section className="space-y-2.5 px-4 pt-3">
        {query.isLoading && <SkeletonList count={5} />}
        {query.isError && <ErrorState onRetry={() => query.refetch()} />}
        {query.isSuccess && query.data.length === 0 && (
          <EmptyState
            icon={Tag}
            title="Keine Angebote gefunden"
            description="Für deine Auswahl wurden diese Woche keine Angebote gefunden."
            action={
              <button
                onClick={() => setFilter("alle")}
                className="inline-flex h-11 items-center rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground"
              >
                Filter zurücksetzen
              </button>
            }
          />
        )}
        {query.data?.map((o) => <OfferRow key={`${o.productId}-${o.marketId}`} offer={o} />)}
      </section>
    </div>
  );
}

import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { CalendarDays, ChevronDown, Search, Store, Tag } from "lucide-react";
import { PageHeader } from "@/components/AppShell";
import { CategoryIcon } from "@/components/lokero/CategoryIcon";
import { OfferRow } from "@/components/lokero/OfferCard";
import { EmptyState, ErrorState, SkeletonList } from "@/components/lokero/States";
import { fetchOffers, fetchOfferWeek, type OfferView } from "@/services/lokero-api";
import { fetchCategories } from "@/services/lokero-categories-api";
import type { CategoryId } from "@/data/lokero";
import { formatDateRange } from "@/lib/format";
import { useStore } from "@/lib/app-store";
import { cn } from "@/lib/utils";

type OfferSearch = { category?: CategoryId };

const OFFERS_SEARCH_KEY = "lokero:offers:search";
const OFFERS_OPEN_CATEGORIES_KEY = "lokero:offers:open-categories";

export const Route = createFileRoute("/angebote")({
  validateSearch: (search: Record<string, unknown>): OfferSearch => ({
    ...(search["category"] ? { category: search["category"] as CategoryId } : {}),
  }),
  head: () => ({ meta: [{ title: "Aktuelle Angebote deiner Märkte – Spareno" }] }),
  component: OffersScreen,
});

function readStoredSearch() {
  if (typeof window === "undefined") return "";
  return window.sessionStorage.getItem(OFFERS_SEARCH_KEY) ?? "";
}

function readStoredCategories(initialCategory?: CategoryId) {
  const next = new Set<string>();
  if (typeof window !== "undefined") {
    try {
      const stored = JSON.parse(window.sessionStorage.getItem(OFFERS_OPEN_CATEGORIES_KEY) ?? "[]");
      if (Array.isArray(stored)) stored.forEach((value) => next.add(String(value)));
    } catch {
      // Ignore invalid legacy session state.
    }
  }
  if (initialCategory) return new Set([initialCategory]);
  return next;
}

function offerDisplayKey(offer: OfferView) {
  const chain = String(offer.market.chain ?? "").trim().toLocaleUpperCase("de");
  const price = Number.isFinite(offer.price) ? offer.price.toFixed(4) : String(offer.price);
  const oldPrice = offer.oldPrice == null ? "" : Number(offer.oldPrice).toFixed(4);
  return [offer.productId, chain, price, oldPrice, offer.validFrom ?? "", offer.validUntil ?? ""].join("|");
}

function preferredOffer(current: OfferView, candidate: OfferView) {
  const currentDistance = Number(current.market.distanceKm ?? 0);
  const candidateDistance = Number(candidate.market.distanceKm ?? 0);
  if (candidateDistance > 0 && (currentDistance <= 0 || candidateDistance < currentDistance)) return candidate;
  return current;
}

export function dedupeOffersForDisplay(offers: OfferView[]) {
  const deduped = new Map<string, OfferView>();
  for (const offer of offers) {
    const key = offerDisplayKey(offer);
    const existing = deduped.get(key);
    deduped.set(key, existing ? preferredOffer(existing, offer) : offer);
  }
  return [...deduped.values()];
}

function OffersScreen() {
  const initial = Route.useSearch();
  const { favoriteMarkets } = useStore();
  const [search, setSearch] = useState(readStoredSearch);
  const [openCategories, setOpenCategories] = useState<Set<string>>(
    () => readStoredCategories(initial.category),
  );
  const [selectedCategory, setSelectedCategory] = useState<string | null>(initial.category ?? null);
  const initialScrollDone = useRef(false);
  const favoriteMarketKey = useMemo(() => [...favoriteMarkets].sort().join(","), [favoriteMarkets]);
  const hasFavoriteMarkets = favoriteMarkets.length > 0;

  const categories = useQuery({ queryKey: ["lokero-categories"], queryFn: fetchCategories });
  const query = useQuery({
    queryKey: ["offers", favoriteMarketKey],
    queryFn: () => fetchOffers({ categoryId: null, tag: null, marketIds: favoriteMarkets }),
    enabled: hasFavoriteMarkets,
  });
  const week = useQuery({
    queryKey: ["offer-week"],
    queryFn: fetchOfferWeek,
    enabled: hasFavoriteMarkets,
  });

  useEffect(() => {
    if (typeof window !== "undefined") window.sessionStorage.setItem(OFFERS_SEARCH_KEY, search);
  }, [search]);

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.sessionStorage.setItem(OFFERS_OPEN_CATEGORIES_KEY, JSON.stringify([...openCategories]));
    }
  }, [openCategories]);

  const groups = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase("de");
    const categoryRows = categories.data ?? [];
    const categoryLabels = new Map(categoryRows.map((category) => [category.id, category.label.toLocaleLowerCase("de")]));
    const rows = dedupeOffersForDisplay(query.data ?? []).filter((offer) => {
      if (!needle) return true;
      const product = offer.product;
      const categoryLabel = categoryLabels.get(product.category) ?? "";
      return [product.name, product.brand, product.detail, product.amount, categoryLabel]
        .filter(Boolean)
        .some((value) => String(value).toLocaleLowerCase("de").includes(needle));
    });
    return categoryRows
      .map((category) => ({
        category,
        offers: rows.filter((offer) => offer.product.category === category.id),
      }))
      .filter((group) => group.offers.length > 0);
  }, [query.data, categories.data, search]);

  useEffect(() => {
    if (!initial.category || initialScrollDone.current || groups.length === 0) return;
    const exists = groups.some((group) => group.category.id === initial.category);
    if (!exists) return;
    setSearch("");
    setSelectedCategory(initial.category);
    setOpenCategories(new Set([initial.category]));
    initialScrollDone.current = true;
    window.requestAnimationFrame(() => {
      document.getElementById(`offer-category-${initial.category}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }, [groups, initial.category]);

  const visibleOfferCount = groups.reduce((sum, group) => sum + group.offers.length, 0);
  const searchActive = search.trim().length > 0;

  const focusCategory = (categoryId: string) => {
    setSearch("");
    setSelectedCategory(categoryId);
    setOpenCategories(new Set([categoryId]));
    window.requestAnimationFrame(() => {
      document.getElementById(`offer-category-${categoryId}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  };

  const toggleCategory = (categoryId: string) => {
    setOpenCategories((current) => {
      const next = new Set(current);
      if (next.has(categoryId)) {
        next.delete(categoryId);
        if (selectedCategory === categoryId) setSelectedCategory(null);
      } else {
        next.add(categoryId);
      }
      return next;
    });
  };

  return (
    <div>
      <PageHeader title="Angebote" />

      <div className="space-y-3 px-4 pt-3">
        {!hasFavoriteMarkets ? (
          <div className="rounded-xl border border-border bg-surface px-3 py-3">
            <div className="flex items-start gap-2.5">
              <Store className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
              <div className="min-w-0 flex-1">
                <p className="text-[12px] font-semibold text-navy">Wähle zuerst deine Märkte aus</p>
                <p className="mt-1 text-[12px] leading-relaxed text-muted-foreground">
                  Damit Angebote eindeutig zu deiner Auswahl passen, zeigen wir hier erst Angebote, sobald du mindestens einen Markt favorisiert hast.
                </p>
              </div>
            </div>
            <Link to="/maerkte" className="mt-3 inline-flex h-10 items-center rounded-xl bg-primary px-4 text-[12px] font-semibold text-primary-foreground">
              Märkte auswählen
            </Link>
          </div>
        ) : (
          <>
            <label className="flex h-11 items-center gap-2 rounded-xl border border-border bg-surface px-3">
              <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="sr-only">Angebote durchsuchen</span>
              <input
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value);
                  setSelectedCategory(null);
                }}
                placeholder="Produkte oder Angebote suchen"
                className="min-w-0 flex-1 bg-transparent text-[13px] text-navy outline-none placeholder:text-muted-foreground"
              />
            </label>

            <section>
              <div className="mb-2 flex items-baseline justify-between gap-3">
                <h2 className="text-[13px] font-semibold text-navy">Kategorien</h2>
                <span className="text-[10px] text-muted-foreground">Seitlich wischen</span>
              </div>
              <div className="-mx-4 overflow-x-auto px-4 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                <div className="grid w-max auto-cols-[92px] grid-flow-col grid-rows-2 gap-2 pr-4">
                  {(categories.data ?? []).map((category) => {
                    const active = selectedCategory === category.id;
                    return (
                      <button
                        key={category.id}
                        type="button"
                        onClick={() => focusCategory(category.id)}
                        aria-pressed={active}
                        className={cn(
                          "flex h-[74px] w-[92px] flex-col items-center justify-center gap-1.5 rounded-xl border px-1 text-center transition-colors",
                          active
                            ? "border-primary bg-primary/[0.07] text-primary"
                            : "border-border bg-surface text-navy active:bg-muted-surface",
                        )}
                      >
                        <span className={cn("grid h-8 w-8 place-items-center rounded-lg", active ? "bg-primary/10" : "bg-primary-soft text-primary")}>
                          <CategoryIcon categoryId={category.id as CategoryId} className="h-4.5 w-4.5" />
                        </span>
                        <span className="line-clamp-2 text-[10px] font-medium leading-tight">{category.label}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            </section>

            <div className="flex items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2.5">
              <CalendarDays className="h-4 w-4 shrink-0 text-primary" />
              <p className="tabular min-w-0 flex-1 truncate text-[12px] font-medium text-navy">
                {week.data ? `Diese Woche: ${formatDateRange(week.data.from, week.data.until)}` : "Angebotszeitraum wird geladen …"}
              </p>
            </div>
          </>
        )}
      </div>

      {hasFavoriteMarkets && (
        <div className="px-4 pt-3">
          {query.isLoading && <SkeletonList count={5} />}
          {query.isError && <ErrorState onRetry={() => query.refetch()} />}
          {query.isSuccess && visibleOfferCount === 0 && (
            <EmptyState
              icon={Tag}
              title="Keine Angebote gefunden"
              description={search ? "Für deine Suche wurden keine Angebote gefunden." : "Für deine ausgewählten Märkte wurden diese Woche keine Angebote gefunden."}
              action={search ? <button onClick={() => setSearch("")} className="inline-flex h-11 items-center rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground">Suche löschen</button> : undefined}
            />
          )}

          <div className="space-y-2.5">
            {groups.map(({ category, offers }) => {
              const open = searchActive || openCategories.has(category.id);
              return (
                <section id={`offer-category-${category.id}`} key={category.id} className="scroll-mt-24 overflow-hidden rounded-xl border border-border bg-surface">
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
      )}
    </div>
  );
}

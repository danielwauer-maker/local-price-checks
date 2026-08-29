import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ChevronLeft, Search as SearchIcon } from "lucide-react";
import { SearchBar } from "@/components/lokero/SearchBar";
import { ProductThumb } from "@/components/lokero/CategoryIcon";
import { MarketLogo } from "@/components/lokero/MarketLogo";
import { EmptyState, SkeletonList } from "@/components/lokero/States";
import { bestPriceFor, getMarket, search, suggest } from "@/services/lokero-api";
import { formatEuro } from "@/lib/format";

type SearchParams = { q?: string };

export const Route = createFileRoute("/suche")({
  validateSearch: (s: Record<string, unknown>): SearchParams =>
    s["q"] ? { q: String(s["q"]) } : {},
  head: () => ({
    meta: [
      { title: "Produkte & Angebote suchen – Spareno" },
      {
        name: "description",
        content:
          "Suche Produkte, Kategorien und Angebote in deinen lokalen Märkten – inklusive verwandter Produkte und Vorschlägen.",
      },
      { property: "og:title", content: "Suche – Spareno" },
      { property: "og:description", content: "Produkte, Kategorien und Angebote lokal finden." },
    ],
  }),
  component: SearchScreen,
});

function SearchScreen() {
  const { q } = Route.useSearch();
  const navigate = useNavigate();
  const [query, setQuery] = useState(q ?? "");

  const updateQuery = (value: string) => {
    setQuery(value);
    void navigate({
      to: "/suche",
      search: value.trim() ? { q: value } : {},
      replace: true,
    });
  };

  const results = useQuery({
    queryKey: ["search", query],
    queryFn: () => search(query),
    enabled: query.trim().length > 0,
  });
  const suggestions = query.trim().length > 0 ? suggest(query) : [];

  return (
    <div>
      <header className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-2 bg-surface px-4 pb-3 pt-[max(1rem,env(safe-area-inset-top))]">
        <button
          onClick={() => navigate({ to: "/" })}
          aria-label="Zurück"
          className="tap-target grid place-items-center rounded-xl text-navy"
        >
          <ChevronLeft className="h-5 w-5" />
        </button>
        <SearchBar defaultValue={query} autoFocus onChange={updateQuery} />
      </header>

      <div className="space-y-4 px-4 pt-4">
        {query.trim() === "" && (
          <EmptyState
            icon={SearchIcon}
            title="Wonach suchst du?"
            description="Suche nach Produkten, Marken oder ganzen Kategorien wie „Fisch“ oder „Käse“."
          />
        )}

        {query.trim() !== "" && suggestions.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {suggestions.map((s) => (
              <button
                key={s}
                onClick={() => updateQuery(s)}
                className="rounded-full border border-border bg-surface px-3 py-1.5 text-[12px] text-muted-foreground"
              >
                {s}
              </button>
            ))}
          </div>
        )}

        {results.isLoading && <SkeletonList count={4} />}

        {results.data && results.data.categories.length > 0 && (
          <section>
            <h2 className="mb-2 text-[13px] font-semibold text-navy">Kategorien</h2>
            <div className="flex flex-wrap gap-2">
              {results.data.categories.map((c) => (
                <Link
                  key={c.id}
                  to="/angebote"
                  search={{ category: c.id }}
                  className="rounded-full bg-primary-soft px-3 py-1.5 text-[12px] font-semibold text-primary"
                >
                  {c.label}
                </Link>
              ))}
            </div>
          </section>
        )}

        {results.data && (
          <section className="space-y-2.5">
            <h2 className="text-[13px] font-semibold text-navy">Produkte</h2>
            {results.data.products.length === 0 && (
              <EmptyState
                icon={SearchIcon}
                title="Keine Treffer"
                description="Versuche einen anderen Begriff oder stöbere in den Angeboten."
              />
            )}
            {results.data.products.map((p) => {
              const best = bestPriceFor(p.id);
              const market = best ? getMarket(best.marketId) : undefined;
              return (
                <Link
                  key={p.id}
                  to="/produkt/$productId"
                  params={{ productId: p.id }}
                  className="card-surface flex items-center gap-3 p-3"
                >
                  <ProductThumb categoryId={p.category} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] font-semibold text-navy">{p.name}</p>
                    <p className="truncate text-[11px] text-muted-foreground">
                      {p.brand} · {p.amount}
                    </p>
                  </div>
                  <div className="shrink-0 text-right">
                    {best && (
                      <p className="tabular text-[14px] font-bold text-navy">
                        {formatEuro(best.price)}
                      </p>
                    )}
                    {market && <MarketLogo chain={market.chain} size="xs" className="mt-1" />}
                  </div>
                </Link>
              );
            })}
          </section>
        )}
      </div>
    </div>
  );
}

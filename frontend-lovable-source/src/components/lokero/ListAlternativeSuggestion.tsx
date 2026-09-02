import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRightLeft, X } from "lucide-react";
import type { AlternativeKind, Chain, Product } from "@/data/lokero";
import { formatEuro } from "@/lib/format";
import { ProductImage } from "./ProductImage";
import { MarketLogo } from "./MarketLogo";

export type ListAlternative = {
  product: Product;
  price: number;
  market: { id: string; name: string; chain: Chain };
  kind: AlternativeKind;
  reason?: string;
  confidence?: number;
};

const DISMISSED_KEY = "spareno.list-alternative-dismissed.v1";

function readDismissed(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const parsed = JSON.parse(window.localStorage.getItem(DISMISSED_KEY) || "[]") as unknown;
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
}

async function fetchListAlternatives(productId: string): Promise<ListAlternative[]> {
  try {
    const response = await fetch(`/api/lokero/list/products/${encodeURIComponent(productId)}/alternatives`, {
      credentials: "include",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) return [];
    return (await response.json()) as ListAlternative[];
  } catch {
    return [];
  }
}

export function ListAlternativeSuggestion({
  productId,
  onReplace,
}: {
  productId: string;
  onReplace: (alternative: ListAlternative) => void;
}) {
  const [dismissed, setDismissed] = useState<string[]>(readDismissed);
  const query = useQuery({
    queryKey: ["list-product-alternatives", productId],
    queryFn: () => fetchListAlternatives(productId),
    staleTime: 5 * 60_000,
  });
  const alternative = useMemo(
    () => (query.data ?? []).find((row) => !dismissed.includes(`${productId}:${row.product.id}`)),
    [query.data, dismissed, productId],
  );

  if (!alternative) return null;

  const dismiss = () => {
    const key = `${productId}:${alternative.product.id}`;
    const next = Array.from(new Set([...dismissed, key]));
    setDismissed(next);
    try { window.localStorage.setItem(DISMISSED_KEY, JSON.stringify(next.slice(-250))); } catch { /* best effort */ }
  };

  return (
    <div className="mx-3 mb-3 rounded-xl border border-primary/20 bg-primary/[0.035] p-2.5">
      <div className="flex items-start gap-2.5">
        <ProductImage product={alternative.product} size="sm" />
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-primary">Passendes aktuelles Angebot?</p>
          <p className="line-clamp-2 text-[12px] font-semibold text-navy">{alternative.product.name}</p>
          <div className="mt-1 flex min-w-0 items-center gap-1.5">
            <MarketLogo chain={alternative.market.chain} size="xs" />
            <span className="truncate text-[10px] text-muted-foreground">{alternative.market.name}</span>
            <span className="tabular ml-auto shrink-0 text-[12px] font-bold text-primary-deep">{formatEuro(alternative.price)}</span>
          </div>
          {alternative.reason && <p className="mt-1 text-[10px] text-muted-foreground">{alternative.reason}</p>}
        </div>
      </div>
      <div className="mt-2 flex gap-2">
        <button type="button" onClick={() => onReplace(alternative)} className="inline-flex h-9 flex-1 items-center justify-center gap-1.5 rounded-lg bg-primary px-3 text-[11px] font-semibold text-primary-foreground">
          <ArrowRightLeft className="h-3.5 w-3.5" /> Ersetzen
        </button>
        <button type="button" onClick={dismiss} className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-border bg-surface px-3 text-[11px] font-semibold text-muted-foreground">
          <X className="h-3.5 w-3.5" /> Nicht verwenden
        </button>
      </div>
    </div>
  );
}

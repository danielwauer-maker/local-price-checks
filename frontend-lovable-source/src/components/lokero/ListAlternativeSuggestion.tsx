import { useMemo, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { ArrowRightLeft, Loader2, X } from "lucide-react";
import { toast } from "sonner";
import type { AlternativeKind, Chain, Product } from "@/data/lokero";
import { formatEuro } from "@/lib/format";
import { fetchOffers } from "@/services/lokero-api";
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
  const navigate = useNavigate();
  const [dismissed, setDismissed] = useState<string[]>(readDismissed);
  const [busyAction, setBusyAction] = useState<"details" | "replace" | null>(null);
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

  const hydrateCurrentOffer = async () => {
    const rows = await fetchOffers({ query: alternative.product.name });
    return rows.some(
      (row) => row.productId === alternative.product.id && row.marketId === alternative.market.id,
    );
  };

  const openDetails = async () => {
    if (busyAction) return;
    setBusyAction("details");
    try {
      const current = await hydrateCurrentOffer();
      if (!current) {
        toast.error("Dieses Angebot ist aktuell nicht mehr verfügbar.");
        return;
      }
      await navigate({ to: "/produkt/$productId", params: { productId: alternative.product.id } });
    } catch {
      toast.error("Artikeldetails konnten nicht geladen werden.");
    } finally {
      setBusyAction(null);
    }
  };

  const replace = async () => {
    if (busyAction) return;
    setBusyAction("replace");
    try {
      const current = await hydrateCurrentOffer();
      if (!current) {
        toast.error("Dieses Angebot ist aktuell nicht mehr verfügbar. Dein bisheriger Artikel bleibt auf der Liste.");
        return;
      }
      onReplace(alternative);
    } catch {
      toast.error("Das Angebot konnte nicht bestätigt werden. Dein bisheriger Artikel bleibt auf der Liste.");
    } finally {
      setBusyAction(null);
    }
  };

  return (
    <div className="mx-3 mb-3 rounded-xl border border-primary/20 bg-primary/[0.035] p-2.5">
      <button
        type="button"
        onClick={openDetails}
        disabled={busyAction !== null}
        className="flex w-full items-start gap-2.5 rounded-lg text-left disabled:opacity-70"
        aria-label={`${alternative.product.name} Details öffnen`}
      >
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
          <p className="mt-1 text-[9px] font-medium text-primary">Antippen für Details</p>
        </div>
        {busyAction === "details" && <Loader2 className="mt-1 h-4 w-4 shrink-0 animate-spin text-primary" />}
      </button>
      <div className="mt-2 flex gap-2">
        <button type="button" onClick={replace} disabled={busyAction !== null} className="inline-flex h-9 flex-1 items-center justify-center gap-1.5 rounded-lg bg-primary px-3 text-[11px] font-semibold text-primary-foreground disabled:opacity-60">
          {busyAction === "replace" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ArrowRightLeft className="h-3.5 w-3.5" />} Ersetzen
        </button>
        <button type="button" onClick={dismiss} disabled={busyAction !== null} className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-border bg-surface px-3 text-[11px] font-semibold text-muted-foreground disabled:opacity-60">
          <X className="h-3.5 w-3.5" /> Nicht verwenden
        </button>
      </div>
    </div>
  );
}

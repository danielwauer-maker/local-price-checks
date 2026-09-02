import { useMemo, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { ArrowRightLeft, Loader2, X } from "lucide-react";
import { toast } from "sonner";
import { fetchOffers, type OfferView } from "@/services/lokero-api";
import { formatEuro } from "@/lib/format";
import { ProductImage } from "./ProductImage";
import { MarketLogo } from "./MarketLogo";

const DISMISSED_KEY = "spareno.manual-offer-dismissed.v1";

function readDismissed(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const parsed = JSON.parse(window.localStorage.getItem(DISMISSED_KEY) || "[]") as unknown;
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch { return []; }
}

export function ManualOfferSuggestion({ itemId, name, onReplace }: { itemId: string; name: string; onReplace: (offer: OfferView) => void }) {
  const navigate = useNavigate();
  const [dismissed, setDismissed] = useState<string[]>(readDismissed);
  const [busy, setBusy] = useState<"details" | "replace" | null>(null);
  const query = useQuery({
    queryKey: ["manual-list-offers", name.toLocaleLowerCase("de-DE")],
    queryFn: () => fetchOffers({ query: name }),
    enabled: name.trim().length >= 2,
    staleTime: 60_000,
  });
  const offers = useMemo(() => {
    const seen = new Set<string>();
    return [...(query.data ?? [])]
      .sort((a, b) => a.price - b.price)
      .filter((row) => {
        const key = `${itemId}:${row.productId}:${row.marketId}`;
        if (dismissed.includes(key) || seen.has(row.productId)) return false;
        seen.add(row.productId);
        return true;
      });
  }, [query.data, dismissed, itemId]);
  const offer = offers[0];
  if (!offer) return null;

  const key = `${itemId}:${offer.productId}:${offer.marketId}`;
  const dismiss = () => {
    const next = Array.from(new Set([...dismissed, key]));
    setDismissed(next);
    try { window.localStorage.setItem(DISMISSED_KEY, JSON.stringify(next.slice(-300))); } catch { /* best effort */ }
  };
  const openDetails = async () => {
    if (busy) return;
    setBusy("details");
    try { await navigate({ to: "/produkt/$productId", params: { productId: offer.productId } }); }
    catch { toast.error("Artikeldetails konnten nicht geöffnet werden."); }
    finally { setBusy(null); }
  };
  const replace = () => {
    if (busy) return;
    setBusy("replace");
    try { onReplace(offer); }
    finally { setBusy(null); }
  };

  return (
    <div className="mx-3 mb-3 rounded-xl border border-primary/20 bg-primary/[0.035] p-2.5">
      <button type="button" onClick={openDetails} disabled={busy !== null} className="flex w-full items-start gap-2.5 rounded-lg text-left disabled:opacity-70">
        <ProductImage product={offer.product} size="sm" />
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-primary">Passendes aktuelles Angebot?</p>
          <p className="line-clamp-2 text-[12px] font-semibold text-navy">{offer.product.name}</p>
          <div className="mt-1 flex min-w-0 items-center gap-1.5"><MarketLogo chain={offer.market.chain} size="xs" /><span className="truncate text-[10px] text-muted-foreground">{offer.market.name}</span><span className="tabular ml-auto shrink-0 text-[12px] font-bold text-primary-deep">{formatEuro(offer.price)}</span></div>
          <p className="mt-1 text-[10px] text-muted-foreground">Passend zu deiner freien Eingabe „{name}“</p>
          <p className="mt-1 text-[9px] font-medium text-primary">Antippen für Details</p>
        </div>
        {busy === "details" && <Loader2 className="mt-1 h-4 w-4 shrink-0 animate-spin text-primary" />}
      </button>
      <div className="mt-2 flex gap-2">
        <button type="button" onClick={replace} disabled={busy !== null} className="inline-flex h-9 flex-1 items-center justify-center gap-1.5 rounded-lg bg-primary px-3 text-[11px] font-semibold text-primary-foreground disabled:opacity-60"><ArrowRightLeft className="h-3.5 w-3.5" /> Ersetzen</button>
        <button type="button" onClick={dismiss} disabled={busy !== null} className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-border bg-surface px-3 text-[11px] font-semibold text-muted-foreground disabled:opacity-60"><X className="h-3.5 w-3.5" /> Nicht verwenden</button>
      </div>
    </div>
  );
}

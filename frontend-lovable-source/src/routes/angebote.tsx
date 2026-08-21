import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, Eye, Heart, Search, ShoppingBasket, TestTube2 } from "lucide-react";
import { PageHeader } from "@/components/AppShell";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useActiveMarketIds, useStore } from "@/lib/app-store";
import { currentOffers, formatEuro } from "@/data/demo";
import { groupIdenticalOffers, marketSummary, type GroupedOffer } from "@/lib/offer-groups";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

export const Route = createFileRoute("/angebote")({
  head: () => ({ meta: [{ title: "Aktuelle Angebote deiner Märkte – LocalPrices" }] }),
  component: OffersPage,
});

type ReviewMeta = {
  productId: string;
  marketId: string;
  offerId: string;
  provenanceId: number | null;
  prospectArchiveId: number | null;
  prospectPage: number | null;
  prospectPages?: number[];
  sourceText: string | null;
  reviewStatus: "correct" | "incorrect" | null;
  reviewIssueType: string | null;
  reviewNotes: string | null;
  auditUrl?: string;
};

function reviewKey(productId: string, marketId: string) {
  return `${productId}:${marketId}`;
}

function OffersPage() {
  const activeIds = useActiveMarketIds();
  const { basket, toggleBasket, productFavorites, toggleProductFavorite } = useStore();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [reviewMode, setReviewMode] = useState(false);
  const [reviewMeta, setReviewMeta] = useState<Record<string, ReviewMeta>>({});
  const [detail, setDetail] = useState<GroupedOffer | null>(null);
  const [savingReview, setSavingReview] = useState<number | null>(null);

  const rawOffers = useMemo(() => {
    if (activeIds.length === 0) return [];
    const q = query.trim().toLowerCase();
    return currentOffers(activeIds).filter(
      (o) => q === "" || o.product.name.toLowerCase().includes(q) || o.product.brand.toLowerCase().includes(q),
    );
  }, [activeIds, query]);

  const offers = useMemo<GroupedOffer[]>(() => {
    if (!reviewMode) return groupIdenticalOffers(rawOffers);
    // QA must judge the exact market offer, not a cross-market display group.
    return rawOffers.map((o) => ({
      key: `qa:${o.product.id}:${o.market.id}:${o.price.offer?.price ?? o.price.price}`,
      product: o.product,
      price: o.price,
      discount: o.discount,
      markets: [o.market],
    }));
  }, [rawOffers, reviewMode]);

  useEffect(() => {
    let live = true;
    if (activeIds.length === 0) {
      setReviewMeta({});
      return () => { live = false; };
    }
    fetch(`/api/offer-reviews?market_ids=${encodeURIComponent(activeIds.join(","))}`)
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`review metadata ${response.status}`)))
      .then((rows: ReviewMeta[]) => {
        if (!live) return;
        setReviewMeta(Object.fromEntries(rows.map((row) => [reviewKey(row.productId, row.marketId), row])));
      })
      .catch((error) => console.error("Offer review metadata failed", error));
    return () => { live = false; };
  }, [activeIds]);

  const groups = useMemo(() => {
    const grouped = new Map<string, GroupedOffer[]>();
    for (const offer of offers) {
      const category = String(offer.product.category || "Sonstiges");
      grouped.set(category, [...(grouped.get(category) ?? []), offer]);
    }
    return [...grouped.entries()].sort((a, b) => a[0].localeCompare(b[0], "de"));
  }, [offers]);

  const reviewStats = useMemo(() => {
    let reviewable = 0;
    let reviewed = 0;
    let errors = 0;
    for (const offer of offers) {
      if (offer.markets.length !== 1) continue;
      const meta = reviewMeta[reviewKey(offer.product.id, offer.markets[0].id)];
      if (!meta?.provenanceId) continue;
      reviewable += 1;
      if (meta.reviewStatus) reviewed += 1;
      if (meta.reviewStatus === "incorrect") errors += 1;
    }
    return { reviewable, reviewed, errors };
  }, [offers, reviewMeta]);

  async function saveQuickReview(offer: GroupedOffer, status: "correct" | "incorrect") {
    const market = offer.markets[0];
    const key = reviewKey(offer.product.id, market.id);
    const meta = reviewMeta[key];
    if (!meta?.provenanceId) {
      toast.error("Für dieses Angebot fehlt noch die Prospekt-Seitenzuordnung.");
      return;
    }
    setSavingReview(meta.provenanceId);
    try {
      const response = await fetch(`/api/offer-reviews/${meta.provenanceId}`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ status }),
      });
      if (!response.ok) throw new Error(`review ${response.status}`);
      const updated = await response.json() as ReviewMeta;
      setReviewMeta((state) => ({ ...state, [key]: { ...meta, ...updated } }));
      toast.success(status === "correct" ? "Als optimal geprüft" : "Für Prospekt-Abgleich als Fehler markiert");
    } catch (error) {
      console.error(error);
      toast.error("Bewertung konnte nicht gespeichert werden.");
    } finally {
      setSavingReview(null);
    }
  }

  const detailMarket = detail?.markets[0];
  const detailMeta = detail && detailMarket ? reviewMeta[reviewKey(detail.product.id, detailMarket.id)] : undefined;
  const productImage = detail ? (detail.product as typeof detail.product & { imageUrl?: string | null }).imageUrl : null;

  return (
    <div>
      <PageHeader
        title="Angebote"
        subtitle={reviewMode
          ? `${reviewStats.reviewed} von ${reviewStats.reviewable} Angeboten geprüft · ${reviewStats.errors} Fehler markiert`
          : `${offers.length} unterschiedliche Aktionen in ${activeIds.length} Märkten`}
      />

      <div className="px-5">
        <div className="flex items-center gap-2 rounded-2xl bg-surface px-4 py-3 shadow-card">
          <Search className="h-4 w-4 text-muted-foreground" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Produkt oder Marke suchen" className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground" />
        </div>
        <button
          onClick={() => setReviewMode((value) => !value)}
          className={cn(
            "mt-3 flex w-full items-center justify-center gap-2 rounded-2xl border px-4 py-3 text-sm font-semibold transition-colors",
            reviewMode ? "border-primary bg-primary-soft text-primary" : "border-border bg-surface text-muted-foreground",
          )}
        >
          <TestTube2 className="h-4 w-4" />
          {reviewMode ? "Prüfmodus beenden" : "Prüfmodus für Scrape-Qualität"}
        </button>
        {reviewMode && (
          <div className="mt-2 rounded-2xl bg-primary-soft/60 px-4 py-3 text-xs text-primary">
            Jedes Marktangebot wird einzeln gezeigt. Mit „Optimal“ bestätigst du die Erkennung; „Fehler“ legt den Artikel für den Prospekt-Abgleich vor.
          </div>
        )}
      </div>

      <section className="mt-4 space-y-3 px-5">
        {groups.map(([category, rows], index) => {
          const expanded = query.trim() !== "" || reviewMode || (open[category] ?? index === 0);
          return <div key={category} className="surface-card overflow-hidden">
            <button onClick={() => setOpen((s) => ({ ...s, [category]: !expanded }))} className="flex w-full items-center gap-3 px-4 py-3.5 text-left">
              <div className="min-w-0 flex-1"><p className="text-sm font-semibold">{category}</p><p className="text-[11px] text-muted-foreground">{rows.length} Artikelangebote</p></div>
              <span className="rounded-full bg-primary-soft px-2.5 py-1 text-xs font-bold text-primary">{rows.length}</span>
              <ChevronDown className={cn("h-4 w-4 text-muted-foreground transition-transform", expanded && "rotate-180")} />
            </button>
            {expanded && <div className="border-t border-border">
              {rows.map((o) => {
                const favorite = productFavorites.includes(o.product.id);
                const inBasket = (basket[o.product.id] ?? 0) > 0;
                const market = o.markets[0];
                const meta = o.markets.length === 1 ? reviewMeta[reviewKey(o.product.id, market.id)] : undefined;
                const imageUrl = (o.product as typeof o.product & { imageUrl?: string | null }).imageUrl;
                return <article key={o.key} onClick={() => setDetail(o)} className="flex cursor-pointer gap-3 border-b border-border p-3 transition-colors last:border-0 hover:bg-secondary/35">
                  <div className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-2xl bg-surface-2 text-3xl">{imageUrl ? <img src={imageUrl} alt={o.product.name} className="h-full w-full object-contain" /> : o.product.emoji}</div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start gap-1"><p className="truncate text-sm font-semibold">{o.product.name}</p><Eye className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" /></div>
                    <p className="text-xs text-muted-foreground">{o.product.brand}{o.product.brand && o.product.unit ? " · " : ""}{o.product.unit}</p>
                    <p className="mt-1 text-[11px] text-muted-foreground">{marketSummary(o.markets)} · bis {o.price.offer!.until}</p>
                    {o.markets.length > 1 && <p className="mt-0.5 text-[11px] font-medium text-primary">In {o.markets.length} ausgewählten Märkten identisch</p>}
                    <div className="mt-1.5 flex items-baseline gap-2"><span className="tabular text-lg font-bold text-deal">{formatEuro(o.price.offer!.price)}</span></div>
                    {reviewMode && (
                      <div className="mt-2 flex flex-wrap items-center gap-2" onClick={(event) => event.stopPropagation()}>
                        <button
                          disabled={!meta?.provenanceId || savingReview === meta?.provenanceId}
                          onClick={() => void saveQuickReview(o, "correct")}
                          className={cn("flex items-center gap-1 rounded-xl px-2.5 py-1.5 text-xs font-semibold", meta?.reviewStatus === "correct" ? "bg-primary text-white" : "bg-primary-soft text-primary", !meta?.provenanceId && "opacity-40")}
                        ><CheckCircle2 className="h-3.5 w-3.5" /> Optimal</button>
                        <button
                          disabled={!meta?.provenanceId || savingReview === meta?.provenanceId}
                          onClick={() => void saveQuickReview(o, "incorrect")}
                          className={cn("flex items-center gap-1 rounded-xl px-2.5 py-1.5 text-xs font-semibold", meta?.reviewStatus === "incorrect" ? "bg-deal text-white" : "bg-deal/10 text-deal", !meta?.provenanceId && "opacity-40")}
                        ><AlertTriangle className="h-3.5 w-3.5" /> Fehler</button>
                        {!meta?.provenanceId && <span className="text-[10px] text-muted-foreground">keine Seiten-Provenance</span>}
                        {meta?.prospectPage && <span className="text-[10px] text-muted-foreground">Prospekt S. {meta.prospectPage}</span>}
                      </div>
                    )}
                  </div>
                  {!reviewMode && <div className="flex flex-col items-center justify-center gap-2" onClick={(event) => event.stopPropagation()}>
                    <button onClick={() => toggleProductFavorite(o.product.id)} className={cn("rounded-full p-2", favorite ? "bg-deal/12 text-deal" : "bg-secondary text-muted-foreground")} aria-label="Favorit"><Heart className={cn("h-4 w-4", favorite && "fill-current")} /></button>
                    <button onClick={() => { toggleBasket(o.product.id); toast.success(inBasket ? `${o.product.name} von der Liste entfernt` : `${o.product.name} auf der Liste`); }} className={cn("rounded-full p-2.5 transition-colors", inBasket ? "bg-primary-soft text-primary" : "bg-secondary text-muted-foreground")} aria-label={inBasket ? "Von Einkaufsliste entfernen" : "Zur Einkaufsliste hinzufügen"}><ShoppingBasket className={cn("h-5 w-5", inBasket && "fill-current/15")} /></button>
                  </div>}
                </article>;
              })}
            </div>}
          </div>;
        })}
        {offers.length === 0 && <p className="surface-card p-6 text-center text-sm text-muted-foreground">{activeIds.length === 0 ? "Wähle zuerst mindestens einen freigegebenen Markt für den Vergleich aus." : "Keine Angebote für diese Auswahl."}</p>}
      </section>

      <Dialog open={Boolean(detail)} onOpenChange={(value) => !value && setDetail(null)}>
        <DialogContent className="max-h-[92vh] max-w-lg overflow-y-auto">
          {detail && detailMarket && <>
            <DialogHeader>
              <DialogTitle className="pr-6 text-xl">{detail.product.name}</DialogTitle>
              <DialogDescription>{detail.product.brand || "Ohne Markenangabe"}{detail.product.unit ? ` · ${detail.product.unit}` : ""}</DialogDescription>
            </DialogHeader>
            <div className="overflow-hidden rounded-2xl bg-surface-2 p-3">
              {productImage ? <img src={productImage} alt={detail.product.name} className="mx-auto max-h-[48vh] w-full object-contain" /> : <div className="flex h-56 items-center justify-center text-7xl">{detail.product.emoji}</div>}
            </div>
            <div className="grid grid-cols-2 gap-3 rounded-2xl bg-secondary/45 p-4 text-sm">
              <div><p className="text-xs text-muted-foreground">Preis</p><p className="text-lg font-bold text-deal">{formatEuro(detail.price.offer!.price)}</p></div>
              <div><p className="text-xs text-muted-foreground">Markt</p><p className="font-semibold">{marketSummary(detail.markets)}</p></div>
              <div><p className="text-xs text-muted-foreground">Packung</p><p>{detail.product.unit || "–"}</p></div>
              <div><p className="text-xs text-muted-foreground">Gültig bis</p><p>{detail.price.offer!.until}</p></div>
            </div>
            {detailMeta?.sourceText && <div><p className="mb-1 text-xs font-semibold text-muted-foreground">Erkannter Prospekttext</p><div className="whitespace-pre-wrap rounded-2xl bg-secondary/45 p-3 text-sm leading-relaxed">{detailMeta.sourceText}</div></div>}
            {detailMeta?.prospectPage && <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground"><span>Prospektseite {detailMeta.prospectPages?.length ? detailMeta.prospectPages.join(", ") : detailMeta.prospectPage}</span>{detailMeta.prospectArchiveId && <a onClick={(event) => event.stopPropagation()} className="font-semibold text-primary underline" target="_blank" rel="noreferrer" href={`/admin/prospect-archive/${detailMeta.prospectArchiveId}/pdf#page=${detailMeta.prospectPage}`}>Originalseite öffnen</a>}</div>}
            {reviewMode && <div className="grid grid-cols-2 gap-2">
              <button disabled={!detailMeta?.provenanceId} onClick={() => void saveQuickReview(detail, "correct")} className={cn("flex items-center justify-center gap-2 rounded-2xl px-4 py-3 font-semibold", detailMeta?.reviewStatus === "correct" ? "bg-primary text-white" : "bg-primary-soft text-primary", !detailMeta?.provenanceId && "opacity-40")}><CheckCircle2 className="h-4 w-4" /> Optimal</button>
              <button disabled={!detailMeta?.provenanceId} onClick={() => void saveQuickReview(detail, "incorrect")} className={cn("flex items-center justify-center gap-2 rounded-2xl px-4 py-3 font-semibold", detailMeta?.reviewStatus === "incorrect" ? "bg-deal text-white" : "bg-deal/10 text-deal", !detailMeta?.provenanceId && "opacity-40")}><AlertTriangle className="h-4 w-4" /> Fehler</button>
            </div>}
            {detailMeta?.reviewStatus === "incorrect" && detailMeta.prospectArchiveId && detailMeta.prospectPage && <a className="block rounded-2xl border border-deal/20 bg-deal/5 px-4 py-3 text-center text-sm font-semibold text-deal" target="_blank" rel="noreferrer" href={`/admin/articles/prospect-audit?store_id=${detailMarket.id}&archive_id=${detailMeta.prospectArchiveId}&page=${detailMeta.prospectPage}`}>Fehler im Prospekt-Abgleich detailliert prüfen</a>}
          </>}
        </DialogContent>
      </Dialog>
    </div>
  );
}

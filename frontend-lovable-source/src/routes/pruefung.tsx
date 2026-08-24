import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Check, ExternalLink, ShieldAlert, X } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/AppShell";
import { ErrorState, SkeletonList } from "@/components/lokero/States";
import {
  fetchMarkets,
  fetchReviewerStatus,
  fetchReviewOffers,
  reviewOffer,
  saveReviewerNormalPrice,
  type ReviewOffer,
} from "@/services/lokero-api";

export const Route = createFileRoute("/pruefung")({
  head: () => ({ meta: [{ title: "Interne Artikelprüfung – Lokero" }] }),
  component: ReviewPage,
});

function value(row: Record<string, unknown> | undefined, key: string) {
  return row?.[key] == null ? "" : String(row[key]);
}

function ReviewCard({ row }: { row: ReviewOffer }) {
  const qc = useQueryClient();
  const [normalPrice, setNormalPrice] = useState("");
  const [savingNormalPrice, setSavingNormalPrice] = useState(false);
  const mutation = useMutation({
    mutationFn: (status: "correct" | "incorrect") => {
      if (!row.provenanceId) throw new Error("Keine Provenance vorhanden");
      return reviewOffer(row.provenanceId, status);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["review-offers"] });
      toast.success("Prüfstatus gespeichert");
    },
    onError: () => toast.error("Prüfstatus konnte nicht gespeichert werden"),
  });

  const productName = value(row.product, "name") || `Produkt ${row.productId}`;
  const marketName = value(row.market, "name") || `Markt ${row.marketId}`;
  const price = row.price && row.price.price != null ? Number(row.price.price).toFixed(2).replace(".", ",") : "–";

  async function saveNormalPrice() {
    const parsed = Number(normalPrice.replace(",", "."));
    const productId = Number(row.productId);
    const storeId = Number(row.marketId);
    if (!Number.isFinite(parsed) || parsed <= 0 || !Number.isInteger(productId) || !Number.isInteger(storeId)) {
      toast.error("Bitte einen gültigen Normalpreis eingeben");
      return;
    }
    setSavingNormalPrice(true);
    try {
      await saveReviewerNormalPrice({ productId, storeId, price: parsed, notes: "In Lokero Artikelprüfung bestätigt" });
      setNormalPrice("");
      toast.success("Normalpreis bestätigt");
    } catch {
      toast.error("Normalpreis konnte nicht gespeichert werden");
    } finally {
      setSavingNormalPrice(false);
    }
  }

  return (
    <article className="card-surface p-3.5">
      <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-3">
        <div className="min-w-0">
          <h2 className="truncate text-[14px] font-semibold text-navy">{productName}</h2>
          <p className="mt-0.5 truncate text-[12px] text-muted-foreground">{marketName}</p>
        </div>
        <div className="tabular text-[16px] font-bold text-navy">{price} €</div>
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
        <div><dt className="text-muted-foreground">Prospektseite</dt><dd className="font-medium text-navy">{row.prospectPages?.length ? row.prospectPages.join(", ") : row.prospectPage ?? "–"}</dd></div>
        <div><dt className="text-muted-foreground">Status</dt><dd className="font-medium text-navy">{row.reviewStatus ?? "ungeprüft"}</dd></div>
        <div><dt className="text-muted-foreground">Offer-ID</dt><dd className="font-medium text-navy">{row.offerId}</dd></div>
        <div><dt className="text-muted-foreground">Provenance</dt><dd className="font-medium text-navy">{row.provenanceId ?? "–"}</dd></div>
      </dl>

      {row.sourceText && (
        <details className="mt-3 rounded-xl bg-muted-surface p-2.5 text-[11px] text-muted-foreground">
          <summary className="cursor-pointer font-semibold text-navy">Quelltext anzeigen</summary>
          <p className="mt-2 whitespace-pre-wrap break-words">{row.sourceText}</p>
        </details>
      )}

      <div className="mt-3 grid grid-cols-2 gap-2">
        <button
          type="button"
          disabled={!row.provenanceId || mutation.isPending}
          onClick={() => mutation.mutate("correct")}
          className="flex h-10 items-center justify-center gap-1.5 rounded-xl bg-primary text-[12px] font-semibold text-primary-foreground disabled:opacity-40"
        >
          <Check className="h-4 w-4" /> korrekt
        </button>
        <button
          type="button"
          disabled={!row.provenanceId || mutation.isPending}
          onClick={() => mutation.mutate("incorrect")}
          className="flex h-10 items-center justify-center gap-1.5 rounded-xl border border-border bg-surface text-[12px] font-semibold text-navy disabled:opacity-40"
        >
          <X className="h-4 w-4" /> falsch
        </button>
      </div>

      <details className="mt-2 rounded-xl border border-border bg-surface p-2.5">
        <summary className="cursor-pointer text-[11px] font-semibold text-navy">Bestätigten Normalpreis erfassen</summary>
        <p className="mt-2 text-[10px] leading-relaxed text-muted-foreground">
          Nur eintragen, wenn der reguläre Marktpreis sicher bekannt ist. Der Angebotspreis selbst wird nicht als Normalpreis übernommen.
        </p>
        <div className="mt-2 flex gap-2">
          <input
            value={normalPrice}
            onChange={(e) => setNormalPrice(e.target.value)}
            inputMode="decimal"
            placeholder="z. B. 2,49"
            aria-label="Bestätigter Normalpreis"
            className="h-10 min-w-0 flex-1 rounded-xl border border-border bg-surface px-3 text-[12px] outline-none"
          />
          <button
            type="button"
            onClick={saveNormalPrice}
            disabled={savingNormalPrice}
            className="h-10 rounded-xl bg-primary px-3 text-[11px] font-semibold text-primary-foreground disabled:opacity-50"
          >
            Speichern
          </button>
        </div>
      </details>

      {row.auditUrl && (
        <a
          href={row.auditUrl}
          target="_blank"
          rel="noreferrer"
          className="mt-2 flex h-9 items-center justify-center gap-1.5 text-[11px] font-semibold text-primary"
        >
          Prospekt-Audit öffnen <ExternalLink className="h-3.5 w-3.5" />
        </a>
      )}
    </article>
  );
}

function ReviewPage() {
  const reviewer = useQuery({ queryKey: ["reviewer-status"], queryFn: fetchReviewerStatus });
  const markets = useQuery({ queryKey: ["review-markets"], queryFn: () => fetchMarkets(50), enabled: reviewer.data?.reviewer === true });
  const marketIds = (markets.data ?? []).map((m) => m.id);
  const offers = useQuery({
    queryKey: ["review-offers", marketIds.join(",")],
    queryFn: () => fetchReviewOffers(marketIds),
    enabled: reviewer.data?.reviewer === true && marketIds.length > 0,
  });

  return (
    <div className="pb-4">
      <PageHeader title="Artikelprüfung" subtitle="Nur auf freigeschalteten Prüfgeräten" />
      <div className="space-y-3 px-4 pt-2">
        {reviewer.isLoading && <SkeletonList count={2} />}
        {reviewer.isError && <ErrorState onRetry={() => reviewer.refetch()} />}
        {reviewer.data && !reviewer.data.reviewer && (
          <section className="card-surface p-5 text-center">
            <ShieldAlert className="mx-auto h-7 w-7 text-muted-foreground" />
            <h2 className="mt-2 text-[14px] font-semibold text-navy">Prüfmodus nicht freigeschaltet</h2>
            <p className="mt-1 text-[12px] text-muted-foreground">Aktiviere den internen Prüfmodus über die versteckte Versionsfreigabe in den Einstellungen.</p>
            <Link to="/einstellungen" className="mt-3 inline-flex h-10 items-center rounded-xl bg-primary px-4 text-[12px] font-semibold text-primary-foreground">Zu Einstellungen</Link>
          </section>
        )}
        {reviewer.data?.reviewer && markets.isLoading && <SkeletonList count={2} />}
        {offers.isLoading && <SkeletonList count={4} />}
        {offers.isError && <ErrorState onRetry={() => offers.refetch()} />}
        {offers.data?.length === 0 && (
          <p className="card-surface p-5 text-center text-[12px] text-muted-foreground">Keine aktuellen Angebote für die gewählten Prüf-Märkte gefunden.</p>
        )}
        {offers.data?.map((row) => <ReviewCard key={`${row.offerId}-${row.provenanceId ?? "none"}`} row={row} />)}
      </div>
    </div>
  );
}

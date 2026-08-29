import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Check, MapPinned, Search, Send } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/AppShell";
import { MarketLogo } from "@/components/lokero/MarketLogo";
import { RegionMap } from "@/components/lokero/RegionMap";
import { SkeletonList } from "@/components/lokero/States";
import { MARKETS, PLANNED_REGIONS, type Chain, type Region } from "@/data/lokero";
import { useStore } from "@/lib/app-store";
import { fetchRegions, notifyRegion } from "@/services/lokero-api";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/regionen")({
  head: () => ({
    meta: [
      { title: "Regionen & Verfügbarkeit – Spareno" },
      {
        name: "description",
        content:
          "Prüfe, ob Spareno in deiner Region verfügbar ist: Marktabdeckung, Status und Vormerkung für neue Regionen.",
      },
      { property: "og:title", content: "Regionen & Verfügbarkeit – Spareno" },
      {
        property: "og:description",
        content: "Marktabdeckung je Region, Status und Vormerkung neuer Regionen.",
      },
    ],
  }),
  component: RegionsPage,
});

const STATUS_LABEL: Record<Region["status"], string> = {
  available: "Verfügbar",
  partial: "Teilweise verfügbar",
  unavailable: "Noch nicht verfügbar",
};

function StatusBadge({ status }: { status: Region["status"] }) {
  return (
    <span
      className={cn(
        "shrink-0 rounded-full px-2 py-1 text-[10px] font-semibold",
        status === "available"
          ? "bg-primary text-primary-foreground"
          : status === "partial"
            ? "bg-info-soft text-info"
            : "border border-border bg-muted-surface text-muted-foreground",
      )}
    >
      {STATUS_LABEL[status]}
    </span>
  );
}

function RegionRow({ region }: { region: Region }) {
  const retailers: Chain[] = region.availableRetailers;
  return (
    <article className="card-surface p-3">
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-[14px] font-semibold text-navy">{region.regionName}</h3>
          <p className="tabular mt-0.5 text-[12px] text-muted-foreground">
            {region.postalCode} · {region.activeMarkets}/{region.totalMarkets} Märkte ·{" "}
            {region.coveragePercentage} % Abdeckung
          </p>
        </div>
        <StatusBadge status={region.status} />
      </div>

      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted-surface">
        <div
          className={cn(
            "h-full rounded-full transition-all duration-200",
            region.status === "available" ? "bg-primary" : "bg-info",
          )}
          style={{ width: `${Math.max(region.coveragePercentage, 2)}%` }}
        />
      </div>

      {retailers.length > 0 ? (
        <ul className="mt-2.5 flex flex-wrap gap-1.5">
          {retailers.map((r) => (
            <li key={r} className="flex items-center gap-1">
              <MarketLogo chain={r} size="xs" />
              <Check className="h-3 w-3 text-primary" aria-label="verfügbar" />
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2.5 text-[12px] text-muted-foreground">
          Noch keine Marktdaten in dieser Region.
        </p>
      )}
    </article>
  );
}

function RegionsPage() {
  const { location, radius } = useStore();
  const [query, setQuery] = useState("");
  const [postalCode, setPostalCode] = useState("");
  const [email, setEmail] = useState("");

  const regions = useQuery({ queryKey: ["regions", query], queryFn: () => fetchRegions(query) });

  async function submitNotify(e: React.FormEvent) {
    e.preventDefault();
    if (!postalCode.trim()) return;
    const mail = email.trim();
    await notifyRegion(
      mail ? { postalCode: postalCode.trim(), email: mail } : { postalCode: postalCode.trim() },
    );
    toast.success("Region vorgemerkt", {
      description: "Wir melden uns, sobald Spareno hier verfügbar ist.",
    });
    setPostalCode("");
    setEmail("");
  }

  return (
    <div className="pb-4">
      <PageHeader title="Regionen" subtitle="Verfügbarkeit & Marktabdeckung" />

      <div className="space-y-4 px-4 pt-1">
        <label className="flex h-11 items-center gap-2 rounded-xl border border-border bg-surface px-3">
          <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="sr-only">Ort oder PLZ suchen</span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ort oder PLZ suchen"
            inputMode="search"
            className="min-w-0 flex-1 bg-transparent text-[14px] outline-none placeholder:text-muted-foreground"
          />
        </label>

        <RegionMap
          center={location}
          radiusKm={radius}
          markets={MARKETS}
          interactive
          className="h-[190px] w-full"
        />

        <section>
          <h2 className="text-[15px] font-semibold text-navy">Regionen im Überblick</h2>
          <div className="mt-2.5 space-y-2.5">
            {regions.isLoading && <SkeletonList count={3} />}
            {regions.data?.map((r) => <RegionRow key={r.postalCode} region={r} />)}
            {regions.data?.length === 0 && (
              <p className="card-surface px-4 py-6 text-center text-[13px] text-muted-foreground">
                Keine Region gefunden. Du kannst sie unten vormerken.
              </p>
            )}
          </div>
        </section>

        <section className="card-surface p-3.5">
          <h2 className="flex items-center gap-1.5 text-[14px] font-semibold text-navy">
            <MapPinned className="h-4 w-4 text-primary" /> Nächste geplante Regionen
          </h2>
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {PLANNED_REGIONS.map((r) => (
              <li
                key={r}
                className="rounded-full bg-muted-surface px-2.5 py-1 text-[12px] font-medium text-navy"
              >
                {r}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[11px] text-muted-foreground">Spareno wird laufend erweitert.</p>
        </section>

        <section id="vormerken" className="card-surface p-3.5">
          <h2 className="text-[14px] font-semibold text-navy">Region vormerken</h2>
          <p className="mt-1 text-[12px] text-muted-foreground">
            Benachrichtige mich, wenn Spareno hier verfügbar ist.
          </p>
          <form onSubmit={submitNotify} className="mt-3 space-y-2">
            <input
              value={postalCode}
              onChange={(e) => setPostalCode(e.target.value)}
              placeholder="PLZ bestätigen, z. B. 56305"
              inputMode="numeric"
              aria-label="Postleitzahl"
              className="h-11 w-full rounded-xl border border-border bg-surface px-3 text-[14px] outline-none placeholder:text-muted-foreground"
            />
            <input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="E-Mail (optional)"
              type="email"
              aria-label="E-Mail-Adresse"
              className="h-11 w-full rounded-xl border border-border bg-surface px-3 text-[14px] outline-none placeholder:text-muted-foreground"
            />
            <button
              type="submit"
              className="tap-target flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-primary text-[14px] font-semibold text-primary-foreground transition-transform duration-150 active:scale-[0.99]"
            >
              <Send className="h-4 w-4" /> Region vormerken
            </button>
          </form>
        </section>
      </div>
    </div>
  );
}

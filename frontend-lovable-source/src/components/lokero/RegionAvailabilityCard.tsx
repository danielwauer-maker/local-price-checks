import { Link } from "@tanstack/react-router";
import { ArrowRight, Bell, CheckCircle2, Clock, MapPinned } from "lucide-react";
import type { Market, Region } from "@/data/lokero";
import { cn } from "@/lib/utils";
import { RegionMap } from "@/components/lokero/RegionMap";

const COPY = {
  available: {
    title: "Deine Region ist verfügbar",
    text: "Lokero ist in deiner Region aktiv. Du kannst Märkte, Angebote und Einkaufsoptimierung jetzt nutzen.",
    cta: "Region ansehen",
    badge: "Verfügbar",
  },
  partial: {
    title: "Deine Region wird gerade ausgebaut",
    text: "Erste Märkte und Angebote sind bereits verfügbar. Die vollständige Abdeckung folgt.",
    cta: "Details ansehen",
    badge: "Teilweise verfügbar",
  },
  unavailable: {
    title: "Deine Region ist noch nicht verfügbar",
    text: "Für deinen Standort sind aktuell noch keine vollständigen Marktdaten vorhanden.",
    cta: "Region vormerken",
    badge: "In Planung",
  },
} as const;

function relativeUpdate(iso: string) {
  const days = Math.round((Date.now() - new Date(iso).getTime()) / 864e5);
  if (days <= 0) return "Heute aktualisiert";
  if (days === 1) return "Gestern aktualisiert";
  return `Vor ${days} Tagen aktualisiert`;
}

export function RegionAvailabilityCard({
  region,
  markets,
  radiusKm,
  compact = false,
}: {
  region: Region;
  markets: Market[];
  radiusKm: number;
  compact?: boolean;
}) {
  const copy = COPY[region.status];
  const tone =
    region.status === "available"
      ? "border-primary/25 bg-primary-soft"
      : region.status === "partial"
        ? "border-info/20 bg-info-soft"
        : "border-border bg-muted-surface";

  const badgeTone =
    region.status === "available"
      ? "bg-primary text-primary-foreground"
      : region.status === "partial"
        ? "bg-info text-white"
        : "bg-surface text-muted-foreground border border-border";

  const Icon = region.status === "available" ? CheckCircle2 : MapPinned;

  return (
    <section className={cn("rounded-2xl border p-3.5", tone)}>
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <span
            className={cn(
              "mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-surface",
              region.status === "available" ? "text-primary" : "text-info",
              region.status === "unavailable" && "text-muted-foreground",
            )}
          >
            <Icon className="h-[18px] w-[18px]" strokeWidth={2} />
          </span>
          <div className="min-w-0">
            <h2 className="text-[14px] font-semibold leading-snug text-navy">{copy.title}</h2>
            <p className="mt-1 text-[12px] leading-relaxed text-muted-foreground">{copy.text}</p>
          </div>
        </div>
        <span
          className={cn(
            "shrink-0 rounded-full px-2 py-1 text-[10px] font-semibold",
            badgeTone,
          )}
        >
          {copy.badge}
        </span>
      </div>

      {!compact && (
        <div className="mt-3 grid grid-cols-[92px_minmax(0,1fr)] gap-3">
          <RegionMap
            center={{ lat: region.lat, lng: region.lng }}
            radiusKm={radiusKm}
            markets={markets}
            className="h-[92px] w-[92px]"
          />
          <div className="flex min-w-0 flex-col justify-center gap-1.5">
            <p className="tabular text-[12px] font-semibold text-navy">
              {region.status === "available"
                ? `${region.activeMarkets} Märkte aktiv`
                : `${region.activeMarkets} von ${region.totalMarkets} Märkten aktiv`}
            </p>
            <p className="flex items-center gap-1 text-[11px] text-muted-foreground">
              <Clock className="h-3 w-3 shrink-0" />
              <span className="truncate">{relativeUpdate(region.lastUpdated)}</span>
            </p>
            <p className="truncate text-[11px] text-muted-foreground">
              {region.regionName} · {region.postalCode}
            </p>
          </div>
        </div>
      )}

      <div className="mt-3 flex gap-2">
        <Link
          to="/regionen"
          className={cn(
            "tap-target flex h-10 flex-1 items-center justify-center gap-1.5 rounded-xl text-[13px] font-semibold transition-transform duration-150 active:scale-[0.99]",
            region.status === "unavailable"
              ? "bg-navy text-white"
              : "bg-surface text-primary-deep border border-border",
          )}
        >
          {copy.cta} <ArrowRight className="h-3.5 w-3.5" />
        </Link>
        {region.status === "unavailable" && (
          <Link
            to="/regionen"
            hash="vormerken"
            aria-label="Benachrichtige mich, wenn Lokero hier verfügbar ist"
            className="tap-target grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-border bg-surface text-navy"
          >
            <Bell className="h-4 w-4" />
          </Link>
        )}
      </div>
    </section>
  );
}

import { useState } from "react";
import { Car, CheckCircle2, ChevronDown, Info } from "lucide-react";
import type { OptimizedStop, OptimizedTrip } from "@/data/lokero";
import { getMarket, getProduct } from "@/services/lokero-api";
import { formatEuro } from "@/lib/format";
import { cn } from "@/lib/utils";
import { MarketLogo } from "./MarketLogo";
import { ProductThumb } from "./CategoryIcon";

export function OptimizedTripSummary({ trip }: { trip: OptimizedTrip }) {
  const coveredItemCount = trip.stops.reduce((sum, stop) => sum + stop.itemCount, 0);
  const noSingleStoreComparison = trip.stops.length > 1 && trip.savings <= 0.01;
  const coverageValue = trip.itemCount > 0 ? `${coveredItemCount}/${trip.itemCount}` : "0";
  const kpis = [
    { value: coverageValue, label: "preislich" },
    { value: formatEuro(trip.total), label: "berechenbar" },
    { value: noSingleStoreComparison ? "–" : formatEuro(trip.savings), label: noSingleStoreComparison ? "Ein-Markt" : "Ersparnis", highlight: !noSingleStoreComparison },
    { value: formatEuro(trip.travelCost), label: "Fahrtkosten" },
  ];

  return (
    <section className="gradient-savings rounded-2xl p-4 text-white shadow-raised">
      <p className="flex items-center gap-1.5 text-[14px] font-semibold">
        <CheckCircle2 className="h-4 w-4" /> Dein optimaler Einkauf
      </p>
      <div className="mt-3 grid grid-cols-4 gap-1.5">
        {kpis.map((k) => (
          <div key={k.label} className="rounded-xl bg-white/12 px-1 py-2 text-center">
            <p
              className={cn(
                "tabular text-[13px] font-bold leading-tight",
                k.highlight && "text-[#BBF7D0]",
              )}
            >
              {k.value}
            </p>
            <p className="mt-0.5 text-[9px] leading-tight text-white/75">{k.label}</p>
          </div>
        ))}
      </div>
      <div className="mt-3 rounded-xl bg-white/12 px-3 py-2 text-center">
        {noSingleStoreComparison ? (
          <>
            <p className="text-[12px] font-semibold">{trip.stops.length} Märkte nötig für alle aktuellen Angebotsartikel</p>
            <p className="mt-0.5 flex items-center justify-center gap-1 text-[10px] text-white/75">
              <Info className="h-3 w-3" /> Kein einzelner Markt deckt aktuell alle {coveredItemCount} preislich vergleichbaren Artikel ab.
            </p>
          </>
        ) : (
          <>
            <p className="text-[12px] font-semibold">
              {trip.combinationLabel} spart dir {formatEuro(trip.savings)}
            </p>
            <p className="mt-0.5 flex items-center justify-center gap-1 text-[10px] text-white/75">
              <Info className="h-3 w-3" /> {trip.savingsExplanation}
            </p>
          </>
        )}
      </div>
      {coveredItemCount < trip.itemCount && (
        <p className="mt-2 text-center text-[10px] text-white/75">
          {coveredItemCount} von {trip.itemCount} Artikeln haben aktuell einen Marktpreis; die übrigen bleiben auf deiner Liste.
        </p>
      )}
    </section>
  );
}

export function TripRouteRow({ trip }: { trip: OptimizedTrip }) {
  return (
    <div className="card-surface tabular flex items-center gap-2 px-3 py-2.5 text-[12px] text-muted-foreground">
      <Car className="h-4 w-4 shrink-0 text-info" />
      Fahrtkosten: {formatEuro(trip.travelCost)} · {trip.stops.length} Stopps ·{" "}
      {trip.distanceKm.toLocaleString("de-DE", { maximumFractionDigits: 1 })} km
    </div>
  );
}

export function ShoppingMarketGroup({ stop }: { stop: OptimizedStop }) {
  const [open, setOpen] = useState(false);
  const market = getMarket(stop.marketId);
  const preview = stop.productIds.slice(0, 5);
  const rest = stop.productIds.length - preview.length;
  if (!market) return null;

  return (
    <article className="card-surface p-3">
      <div className="flex items-center gap-3">
        <MarketLogo chain={market.chain} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-semibold text-navy">{market.name}</p>
          <p className="text-[11px] text-muted-foreground">{stop.itemCount} Artikel</p>
        </div>
        <p className="tabular text-[14px] font-bold text-navy">{formatEuro(stop.total)}</p>
      </div>

      <div className="mt-3 flex gap-2">
        {preview.map((id) => {
          const p = getProduct(id);
          return p ? <ProductThumb key={id} categoryId={p.category} size="sm" /> : null;
        })}
        {rest > 0 && (
          <span className="tabular grid h-10 w-10 place-items-center rounded-xl bg-muted-surface text-[11px] font-semibold text-muted-foreground">
            +{rest}
          </span>
        )}
      </div>

      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="mt-2 flex w-full items-center justify-center gap-1 py-1.5 text-[11px] font-medium text-muted-foreground"
      >
        Details {open ? "ausblenden" : "anzeigen"}
        <ChevronDown className={cn("h-3.5 w-3.5 transition-transform duration-200", open && "rotate-180")} />
      </button>

      {open && (
        <ul className="mt-1 space-y-1.5 border-t border-border pt-2">
          {stop.productIds.map((id) => {
            const p = getProduct(id);
            if (!p) return null;
            return (
              <li key={id} className="flex items-center gap-2 text-[12px]">
                <ProductThumb categoryId={p.category} size="sm" className="h-8 w-8" />
                <span className="min-w-0 flex-1 truncate text-navy">{p.name}</span>
                <span className="text-[11px] text-muted-foreground">{p.amount}</span>
              </li>
            );
          })}
        </ul>
      )}
    </article>
  );
}

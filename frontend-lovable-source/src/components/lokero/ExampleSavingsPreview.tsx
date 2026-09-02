import { Calculator, Info } from "lucide-react";
import type { OptimizedTrip } from "@/data/lokero";
import { formatEuro } from "@/lib/format";

export function ExampleSavingsPreview({ trip, totalItems, compact = false }: { trip?: OptimizedTrip; totalItems: number; compact?: boolean }) {
  const covered = trip?.stops.reduce((sum, stop) => sum + stop.itemCount, 0) ?? 0;
  const currentMerchandise = trip ? Math.max(0, trip.total - trip.travelCost) : 0;
  const average = covered > 0 ? currentMerchandise / covered : 2.4;
  const projectedOptimizedGoods = average * Math.max(totalItems, 12);
  // This is deliberately a transparent preview assumption, not a claimed saving:
  // with broad cross-market coverage we illustrate a 15% single-store price spread.
  const exampleSingleStoreGoods = projectedOptimizedGoods * 1.15;
  const exampleTravel = trip?.travelCost ?? 3.6;
  const exampleOptimizedTotal = projectedOptimizedGoods + exampleTravel;
  const exampleSaving = Math.max(0, exampleSingleStoreGoods - exampleOptimizedTotal);

  if (compact) {
    return (
      <section className="rounded-2xl border border-primary/20 bg-primary/[0.035] p-4">
        <div className="flex items-start gap-3">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-primary-soft text-primary"><Calculator className="h-4.5 w-4.5" /></span>
          <div className="min-w-0 flex-1">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-primary">Beispielrechnung aufgrund weniger Vergleichsdaten</p>
            <p className="mt-1 text-[13px] font-semibold text-navy">So wird Spareno mit dichterer Preisdatenbank vergleichen</p>
            <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">Beispiel: {Math.max(totalItems, 12)} Artikel · optimiert inkl. Fahrt {formatEuro(exampleOptimizedTotal)} · angenommener Ein-Markt-Warenkorb {formatEuro(exampleSingleStoreGoods)} · mögliche Ersparnis {formatEuro(exampleSaving)}.</p>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-2xl border border-primary/20 bg-primary/[0.035] p-4">
      <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-primary"><Calculator className="h-4 w-4" /> Beispielrechnung aufgrund weniger Vergleichsdaten</p>
      <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">Noch fehlen für viele Produkte parallele Preise aus mehreren Märkten. Deshalb zeigt diese Karte bewusst nur, wie die vollständige Optimierung später aussehen kann.</p>
      <div className="mt-3 grid grid-cols-3 gap-2 text-center">
        <div className="rounded-xl bg-surface p-2"><p className="tabular text-[13px] font-bold text-navy">{formatEuro(exampleSingleStoreGoods)}</p><p className="text-[9px] text-muted-foreground">1 Markt · Beispiel</p></div>
        <div className="rounded-xl bg-surface p-2"><p className="tabular text-[13px] font-bold text-navy">{formatEuro(exampleOptimizedTotal)}</p><p className="text-[9px] text-muted-foreground">optimiert inkl. Fahrt</p></div>
        <div className="rounded-xl bg-primary-soft p-2"><p className="tabular text-[13px] font-bold text-primary-deep">{formatEuro(exampleSaving)}</p><p className="text-[9px] text-muted-foreground">Beispiel-Ersparnis</p></div>
      </div>
      <p className="mt-2 flex items-start gap-1 text-[9px] leading-relaxed text-muted-foreground"><Info className="mt-0.5 h-3 w-3 shrink-0" /> Grundlage der Vorschau ist dein aktueller durchschnittlicher Angebotswert; für die Illustration wird ein transparenter Preisunterschied von 15 % zum Ein-Markt-Einkauf angenommen. Dieser Betrag ist keine echte aktuelle Ersparnis.</p>
    </section>
  );
}

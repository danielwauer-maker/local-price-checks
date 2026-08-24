import MapPanel from "@/components/MapPanel";
import type { Market } from "@/data/lokero";
import { cn } from "@/lib/utils";

/**
 * Kleine Regionsvorschau (Standort, Radius, unterstützte Märkte).
 * Bewusst nicht interaktiv – die Karte unterstützt die Card, dominiert sie nicht.
 */
export function RegionMap({
  center,
  radiusKm,
  markets,
  className,
  interactive = false,
}: {
  center: { lat: number; lng: number };
  radiusKm: number;
  markets: Market[];
  className?: string;
  interactive?: boolean;
}) {
  return (
    <div
      aria-hidden={!interactive}
      className={cn(
        "relative overflow-hidden rounded-xl border border-border bg-muted-surface",
        !interactive && "pointer-events-none",
        className,
      )}
    >
      <MapPanel center={center} radiusKm={radiusKm} markets={markets} />
    </div>
  );
}

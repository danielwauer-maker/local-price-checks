import { lazy, Suspense } from "react";
import { ClientOnly } from "@tanstack/react-router";
import type { Market } from "@/data/lokero";

const MarketMap = lazy(() => import("./MarketMap"));

type Props = {
  center: { lat: number; lng: number };
  radiusKm: number;
  markets: Market[];
  activeId?: string | null;
  onSelect?: (id: string) => void;
};

function MapSkeleton() {
  return <div className="h-full w-full animate-pulse bg-muted-surface" />;
}

/** Leaflet lädt erst im Browser – SSR-sicher gekapselt. */
export default function MapPanel(props: Props) {
  return (
    <ClientOnly fallback={<MapSkeleton />}>
      <Suspense fallback={<MapSkeleton />}>
        <MarketMap {...props} />
      </Suspense>
    </ClientOnly>
  );
}

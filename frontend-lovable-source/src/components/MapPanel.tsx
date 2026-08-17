import { Suspense, lazy, useEffect, useState } from "react";
import type { Market } from "@/data/demo";

const MarketMap = lazy(() => import("./MarketMap"));

type Props = {
  center: { lat: number; lng: number };
  radiusKm: number;
  markets: Array<Market & { distance: number }>;
  selected: string[];
  onSelect: (id: string) => void;
  activeId?: string | null;
};

export function MapPanel(props: Props) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  if (!mounted) {
    return <div className="h-full w-full animate-pulse bg-surface-2" />;
  }

  return (
    <Suspense fallback={<div className="h-full w-full animate-pulse bg-surface-2" />}>
      <MarketMap {...props} />
    </Suspense>
  );
}

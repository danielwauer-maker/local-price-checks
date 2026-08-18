import { Suspense, lazy, useEffect, useState } from "react";
import type { CoverageRegion } from "./CoverageMap";

const CoverageMap = lazy(() => import("./CoverageMap"));

export function CoverageMapPanel({ regions, center }: { regions: CoverageRegion[]; center: { lat: number; lng: number } }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) return <div className="h-full w-full animate-pulse bg-surface-2" />;
  return <Suspense fallback={<div className="h-full w-full animate-pulse bg-surface-2" />}><CoverageMap regions={regions} center={center} /></Suspense>;
}

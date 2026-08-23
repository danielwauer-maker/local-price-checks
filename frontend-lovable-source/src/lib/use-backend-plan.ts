import { useEffect, useState } from "react";
import { useActiveMarketIds, useStore } from "@/lib/app-store";
import { apiFetch } from "@/lib/api-client";

export type BackendPlan = {
  stops: Array<{
    market: { id: string; name: string; chain: string; city: string; openUntil: string };
    lines: Array<{
      product: { id: string; name: string; brand: string; unit: string; emoji: string };
      qty: number;
      unitPrice: number;
      isOffer: boolean;
      lineTotal: number;
      saved: number;
    }>;
    total: number;
  }>;
  total: number;
  merchandiseTotal: number;
  travelKm: number;
  travelCost: number;
  singleMarketTotal: number;
  singleMarket: { chain: string; name: string } | null;
  savingsVsSingle: number;
  savingsVsWorst: number;
  offeredItems: number;
  totalItems: number;
  missing: Array<{ product: { id: string; name: string; brand: string; unit: string; emoji: string }; qty: number }>;
};

export const EMPTY_BACKEND_PLAN: BackendPlan = {
  stops: [],
  total: 0,
  merchandiseTotal: 0,
  travelKm: 0,
  travelCost: 0,
  singleMarketTotal: 0,
  singleMarket: null,
  savingsVsSingle: 0,
  savingsVsWorst: 0,
  offeredItems: 0,
  totalItems: 0,
  missing: [],
};

export function useBackendPlan(maxStops: number) {
  const { hydrated, basketEntries } = useStore();
  const activeIds = useActiveMarketIds();
  const [plan, setPlan] = useState<BackendPlan>(EMPTY_BACKEND_PLAN);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!hydrated) return;
    let live = true;
    const timer = window.setTimeout(() => {
      setLoading(true);
      apiFetch(`/api/plan?max_stores=${maxStops}`)
        .then((r) => {
          if (!r.ok) throw new Error(`plan ${r.status}`);
          return r.json() as Promise<BackendPlan>;
        })
        .then((payload) => live && setPlan(payload))
        .catch((error) => console.error("LocalPrices plan failed", error))
        .finally(() => live && setLoading(false));
    }, 200);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [hydrated, basketEntries, activeIds, maxStops]);

  return { plan, loading };
}

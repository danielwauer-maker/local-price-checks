import { useCallback, useEffect, useRef } from "react";
import { useStore } from "@/lib/app-store";
import { fetchAccountState, persistAccountPreferences, type AccountState } from "@/services/lokero-account-api";

function sameSet(a: string[], b: string[]) {
  if (a.length !== b.length) return false;
  const wanted = new Set(b);
  return a.every((item) => wanted.has(item));
}

export function AccountStateSync() {
  const store = useStore();
  const syncing = useRef(false);

  const applyState = useCallback((state: AccountState) => {
    if (!state.linked) return;

    const serverFavorites = state.favoriteProductIds ?? [];
    if (!sameSet(store.favoriteProducts, serverFavorites)) {
      const current = new Set(store.favoriteProducts);
      const wanted = new Set(serverFavorites);
      for (const productId of serverFavorites) {
        if (!current.has(productId)) store.toggleFavoriteProduct(productId);
      }
      for (const productId of store.favoriteProducts) {
        if (!wanted.has(productId)) store.toggleFavoriteProduct(productId);
      }
    }

    const prefs = state.preferences;
    if (!prefs) return;
    if (Math.abs(store.travelCostPerKm - prefs.travelCostPerKm) > 0.0001) {
      store.setTravelCostPerKm(prefs.travelCostPerKm);
    }
    for (const key of ["priceAlerts", "newOffers", "regionAvailable", "favoriteOffers"] as const) {
      if (store.notifications[key] !== prefs.notifications[key]) {
        store.setNotification(key, prefs.notifications[key]);
      }
    }
  }, [store.favoriteProducts, store.notifications, store.travelCostPerKm, store.toggleFavoriteProduct, store.setNotification, store.setTravelCostPerKm]);

  const sync = useCallback(async () => {
    if (syncing.current || !store.hydrated) return;
    syncing.current = true;
    try {
      let state = await fetchAccountState();
      if (!state.linked) return;
      if (!state.preferencesInitialized) {
        state = await persistAccountPreferences({
          initializeOnly: true,
          travelCostPerKm: store.travelCostPerKm,
          notifications: store.notifications,
        });
      }
      applyState(state);
    } catch {
      // Offline/temporary backend failures keep the local state usable.
    } finally {
      syncing.current = false;
    }
  }, [applyState, store.hydrated, store.notifications, store.travelCostPerKm]);

  useEffect(() => {
    if (!store.hydrated) return;
    void sync();
    const interval = window.setInterval(() => void sync(), 15_000);
    const onVisible = () => {
      if (document.visibilityState === "visible") void sync();
    };
    window.addEventListener("focus", sync);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener("focus", sync);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [store.hydrated, sync]);

  return null;
}

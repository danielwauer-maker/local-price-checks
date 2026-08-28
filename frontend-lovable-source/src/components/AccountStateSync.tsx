import { useCallback, useEffect, useRef } from "react";
import { useStore } from "@/lib/app-store";
import { fetchAccountState, persistAccountPreferences, type AccountState } from "@/services/lokero-account-api";
import {
  ACCOUNT_MUTATION_END_EVENT,
  ACCOUNT_MUTATION_START_EVENT,
  ACCOUNT_SYNC_REQUEST_EVENT,
  runWithoutFavoritePersistence,
} from "@/services/lokero-state-api";

function sameSet(a: string[], b: string[]) {
  if (a.length !== b.length) return false;
  const wanted = new Set(b);
  return a.every((item) => wanted.has(item));
}

export function AccountStateSync() {
  const store = useStore();
  const latestStore = useRef(store);
  const syncing = useRef(false);
  const mutationDepth = useRef(0);
  const mutationEpoch = useRef(0);
  const pendingSync = useRef(false);
  latestStore.current = store;

  const applyState = useCallback((state: AccountState) => {
    if (!state.linked) return;
    const currentStore = latestStore.current;

    const serverFavorites = state.favoriteProductIds ?? [];
    if (!sameSet(currentStore.favoriteProducts, serverFavorites)) {
      const current = new Set(currentStore.favoriteProducts);
      const wanted = new Set(serverFavorites);
      runWithoutFavoritePersistence(() => {
        for (const productId of serverFavorites) {
          if (!current.has(productId)) currentStore.toggleFavoriteProduct(productId);
        }
        for (const productId of currentStore.favoriteProducts) {
          if (!wanted.has(productId)) currentStore.toggleFavoriteProduct(productId);
        }
      });
    }

    const prefs = state.preferences;
    if (!prefs) return;
    if (Math.abs(currentStore.travelCostPerKm - prefs.travelCostPerKm) > 0.0001) {
      currentStore.setTravelCostPerKm(prefs.travelCostPerKm);
    }
    for (const key of ["priceAlerts", "newOffers", "regionAvailable", "favoriteOffers"] as const) {
      if (currentStore.notifications[key] !== prefs.notifications[key]) {
        currentStore.setNotification(key, prefs.notifications[key]);
      }
    }
  }, []);

  const sync = useCallback(async () => {
    const currentStore = latestStore.current;
    if (syncing.current || !currentStore.hydrated || mutationDepth.current > 0) {
      pendingSync.current = true;
      return;
    }

    pendingSync.current = false;
    syncing.current = true;
    const startedAtEpoch = mutationEpoch.current;
    try {
      let state = await fetchAccountState();
      if (!state.linked) return;
      if (!state.preferencesInitialized) {
        const latest = latestStore.current;
        state = await persistAccountPreferences({
          initializeOnly: true,
          travelCostPerKm: latest.travelCostPerKm,
          notifications: latest.notifications,
        });
      }

      // Never let an older GET overwrite a heart/settings change that started
      // while this request was in flight. The mutation completion requests a
      // fresh sync instead.
      if (startedAtEpoch !== mutationEpoch.current || mutationDepth.current > 0) {
        pendingSync.current = true;
        return;
      }
      applyState(state);
    } catch {
      // Offline/temporary backend failures keep the local state usable.
    } finally {
      syncing.current = false;
      if (pendingSync.current && mutationDepth.current === 0) {
        window.setTimeout(() => window.dispatchEvent(new Event(ACCOUNT_SYNC_REQUEST_EVENT)), 0);
      }
    }
  }, [applyState]);

  useEffect(() => {
    const onMutationStart = () => {
      mutationDepth.current += 1;
      mutationEpoch.current += 1;
    };
    const onMutationEnd = () => {
      mutationDepth.current = Math.max(0, mutationDepth.current - 1);
    };
    const onSyncRequest = () => {
      pendingSync.current = true;
      void sync();
    };

    window.addEventListener(ACCOUNT_MUTATION_START_EVENT, onMutationStart);
    window.addEventListener(ACCOUNT_MUTATION_END_EVENT, onMutationEnd);
    window.addEventListener(ACCOUNT_SYNC_REQUEST_EVENT, onSyncRequest);
    return () => {
      window.removeEventListener(ACCOUNT_MUTATION_START_EVENT, onMutationStart);
      window.removeEventListener(ACCOUNT_MUTATION_END_EVENT, onMutationEnd);
      window.removeEventListener(ACCOUNT_SYNC_REQUEST_EVENT, onSyncRequest);
    };
  }, [sync]);

  useEffect(() => {
    if (!store.hydrated) return;

    void sync();
    const interval = window.setInterval(() => void sync(), 15_000);
    const onVisible = () => {
      if (document.visibilityState === "visible") void sync();
    };
    const onFocus = () => void sync();

    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [store.hydrated, sync]);

  return null;
}

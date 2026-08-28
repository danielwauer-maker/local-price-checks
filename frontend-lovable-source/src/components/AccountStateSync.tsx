import { useCallback, useEffect, useRef } from "react";
import { useStore } from "@/lib/app-store";
import { fetchAccountState, persistAccountPreferences, type AccountState } from "@/services/lokero-account-api";
import {
  ACCOUNT_MUTATION_END_EVENT,
  ACCOUNT_MUTATION_START_EVENT,
  ACCOUNT_SYNC_REQUEST_EVENT,
  notifyFavoritesChanged,
  runWithoutFavoritePersistence,
} from "@/services/lokero-state-api";

function sameSet(a: string[], b: string[]) {
  if (a.length !== b.length) return false;
  const wanted = new Set(b);
  return a.every((item) => wanted.has(item));
}

export function AccountStateSync() {
  const store = useStore();
  const syncing = useRef(false);
  const pendingSync = useRef(false);
  const mutationDepth = useRef(0);
  const favoriteProductsRef = useRef(store.favoriteProducts);
  const travelCostRef = useRef(store.travelCostPerKm);
  const notificationsRef = useRef(store.notifications);
  const toggleFavoriteRef = useRef(store.toggleFavoriteProduct);
  const setTravelCostRef = useRef(store.setTravelCostPerKm);
  const setNotificationRef = useRef(store.setNotification);

  useEffect(() => { favoriteProductsRef.current = store.favoriteProducts; }, [store.favoriteProducts]);
  useEffect(() => { travelCostRef.current = store.travelCostPerKm; }, [store.travelCostPerKm]);
  useEffect(() => { notificationsRef.current = store.notifications; }, [store.notifications]);
  useEffect(() => { toggleFavoriteRef.current = store.toggleFavoriteProduct; }, [store.toggleFavoriteProduct]);
  useEffect(() => { setTravelCostRef.current = store.setTravelCostPerKm; }, [store.setTravelCostPerKm]);
  useEffect(() => { setNotificationRef.current = store.setNotification; }, [store.setNotification]);

  const applyState = useCallback((state: AccountState) => {
    if (!state.linked) return;

    const serverFavorites = state.favoriteProductIds ?? [];
    const localFavorites = favoriteProductsRef.current;
    const favoritesChanged = !sameSet(localFavorites, serverFavorites);
    if (favoritesChanged) {
      const current = new Set(localFavorites);
      const wanted = new Set(serverFavorites);
      runWithoutFavoritePersistence(() => {
        for (const productId of serverFavorites) {
          if (!current.has(productId)) toggleFavoriteRef.current(productId);
        }
        for (const productId of localFavorites) {
          if (!wanted.has(productId)) toggleFavoriteRef.current(productId);
        }
      });
      favoriteProductsRef.current = [...serverFavorites];
      notifyFavoritesChanged();
    }

    const prefs = state.preferences;
    if (!prefs) return;
    if (Math.abs(travelCostRef.current - prefs.travelCostPerKm) > 0.0001) {
      setTravelCostRef.current(prefs.travelCostPerKm);
      travelCostRef.current = prefs.travelCostPerKm;
    }
    for (const key of ["priceAlerts", "newOffers", "regionAvailable", "favoriteOffers"] as const) {
      if (notificationsRef.current[key] !== prefs.notifications[key]) {
        setNotificationRef.current(key, prefs.notifications[key]);
        notificationsRef.current = { ...notificationsRef.current, [key]: prefs.notifications[key] };
      }
    }
  }, []);

  const sync = useCallback(async () => {
    if (!store.hydrated) return;
    if (mutationDepth.current > 0) {
      pendingSync.current = true;
      return;
    }
    if (syncing.current) {
      pendingSync.current = true;
      return;
    }
    syncing.current = true;
    try {
      let state = await fetchAccountState();
      if (!state.linked || mutationDepth.current > 0) {
        if (mutationDepth.current > 0) pendingSync.current = true;
        return;
      }
      if (!state.preferencesInitialized) {
        state = await persistAccountPreferences({
          initializeOnly: true,
          travelCostPerKm: travelCostRef.current,
          notifications: notificationsRef.current,
        });
        if (mutationDepth.current > 0) {
          pendingSync.current = true;
          return;
        }
      }
      applyState(state);
    } catch {
      // Offline/temporary backend failures keep the cached UI usable.
    } finally {
      syncing.current = false;
      if (pendingSync.current && mutationDepth.current === 0) {
        pendingSync.current = false;
        window.setTimeout(() => void sync(), 40);
      }
    }
  }, [applyState, store.hydrated]);

  useEffect(() => {
    if (!store.hydrated) return;
    const onMutationStart = () => { mutationDepth.current += 1; };
    const onMutationEnd = () => {
      mutationDepth.current = Math.max(0, mutationDepth.current - 1);
      if (mutationDepth.current === 0 && pendingSync.current) window.setTimeout(() => void sync(), 40);
    };
    const onSyncRequest = () => {
      pendingSync.current = true;
      if (mutationDepth.current === 0) window.setTimeout(() => void sync(), 40);
    };
    window.addEventListener(ACCOUNT_MUTATION_START_EVENT, onMutationStart);
    window.addEventListener(ACCOUNT_MUTATION_END_EVENT, onMutationEnd);
    window.addEventListener(ACCOUNT_SYNC_REQUEST_EVENT, onSyncRequest);
    return () => {
      window.removeEventListener(ACCOUNT_MUTATION_START_EVENT, onMutationStart);
      window.removeEventListener(ACCOUNT_MUTATION_END_EVENT, onMutationEnd);
      window.removeEventListener(ACCOUNT_SYNC_REQUEST_EVENT, onSyncRequest);
    };
  }, [store.hydrated, sync]);

  useEffect(() => {
    if (!store.hydrated) return;
    void sync();
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") void sync();
    }, 15_000);
    const onVisible = () => { if (document.visibilityState === "visible") void sync(); };
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

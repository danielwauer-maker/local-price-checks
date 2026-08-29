import { useCallback, useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useStore } from "@/lib/app-store";
import { ACCOUNT_PROFILE_STORAGE_KEY, fetchAccountState, persistAccountPreferences, type AccountState } from "@/services/lokero-account-api";
import {
  ACCOUNT_MUTATION_END_EVENT,
  ACCOUNT_MUTATION_START_EVENT,
  ACCOUNT_SYNC_REQUEST_EVENT,
  notifyFavoritesChanged,
  runWithoutFavoritePersistence,
} from "@/services/lokero-state-api";
import { performanceMark, performanceMeasure } from "@/lib/performance";

function sameSet(a: string[], b: string[]) {
  if (a.length !== b.length) return false;
  const wanted = new Set(b);
  return a.every((item) => wanted.has(item));
}

export function AccountStateSync() {
  const store = useStore();
  const queryClient = useQueryClient();
  const syncing = useRef(false);
  const pendingSync = useRef(false);
  const mutationDepth = useRef(0);
  const mutationGeneration = useRef(0);
  const latestRevision = useRef(0);
  const syncTimer = useRef<number | null>(null);
  const scheduleSyncRef = useRef<(delay?: number) => void>(() => {});
  const favoriteProductsRef = useRef(store.favoriteProducts);
  const favoriteMarketsRef = useRef(store.favoriteMarkets);
  const locationRef = useRef(store.location);
  const radiusRef = useRef(store.radius);
  const travelCostRef = useRef(store.travelCostPerKm);
  const notificationsRef = useRef(store.notifications);
  const toggleFavoriteRef = useRef(store.toggleFavoriteProduct);
  const reconcileAccountStateRef = useRef(store.reconcileAccountState);
  const setTravelCostRef = useRef(store.setTravelCostPerKm);
  const setNotificationRef = useRef(store.setNotification);

  useEffect(() => { favoriteProductsRef.current = store.favoriteProducts; }, [store.favoriteProducts]);
  useEffect(() => { favoriteMarketsRef.current = store.favoriteMarkets; }, [store.favoriteMarkets]);
  useEffect(() => { locationRef.current = store.location; }, [store.location]);
  useEffect(() => { radiusRef.current = store.radius; }, [store.radius]);
  useEffect(() => { travelCostRef.current = store.travelCostPerKm; }, [store.travelCostPerKm]);
  useEffect(() => { notificationsRef.current = store.notifications; }, [store.notifications]);
  useEffect(() => { toggleFavoriteRef.current = store.toggleFavoriteProduct; }, [store.toggleFavoriteProduct]);
  useEffect(() => { reconcileAccountStateRef.current = store.reconcileAccountState; }, [store.reconcileAccountState]);
  useEffect(() => { setTravelCostRef.current = store.setTravelCostPerKm; }, [store.setTravelCostPerKm]);
  useEffect(() => { setNotificationRef.current = store.setNotification; }, [store.setNotification]);

  const applyState = useCallback((state: AccountState) => {
    if (!state.linked) return;

    const serverFavorites = state.favoriteProductIds ?? [];
    const localFavorites = favoriteProductsRef.current;
    if (!sameSet(localFavorites, serverFavorites)) {
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

    const reconcile: {
      location?: { lat: number; lng: number; label: string };
      radius?: number;
      favoriteMarkets?: string[];
    } = {};
    const profile = state.profile;
    if (profile) {
      const nextRadius = Number(profile.radiusKm || 15);
      if (Math.abs(radiusRef.current - nextRadius) > 0.001) {
        reconcile.radius = nextRadius;
        radiusRef.current = nextRadius;
      }
      if (profile.latitude != null && profile.longitude != null) {
        const label = [profile.postalCode, profile.city].filter(Boolean).join(" ") || "Mein Standort";
        const current = locationRef.current;
        if (
          Math.abs(current.lat - profile.latitude) > 0.00001 ||
          Math.abs(current.lng - profile.longitude) > 0.00001 ||
          current.label !== label
        ) {
          const next = { lat: profile.latitude, lng: profile.longitude, label };
          reconcile.location = next;
          locationRef.current = next;
        }
      }
    }

    const serverFavoriteMarkets = state.favoriteMarketIds ?? [];
    if (!sameSet(favoriteMarketsRef.current, serverFavoriteMarkets)) {
      reconcile.favoriteMarkets = [...serverFavoriteMarkets];
      favoriteMarketsRef.current = [...serverFavoriteMarkets];
    }
    if (Object.keys(reconcile).length > 0) {
      reconcileAccountStateRef.current(reconcile);
    }

    if (state.favoritePreferences) {
      queryClient.setQueryData(["favorite-preferences"], state.favoritePreferences);
    }
    void queryClient.invalidateQueries({ queryKey: ["favorite-families"] });
    void queryClient.invalidateQueries({ queryKey: ["favorite-matched-offers"] });
    void queryClient.invalidateQueries({ queryKey: ["favorite-markets"] });

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
  }, [queryClient]);

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
    const requestedGeneration = mutationGeneration.current;
    performanceMark("account-state-start");
    try {
      let state = await fetchAccountState();
      if (
        !state.linked ||
        mutationDepth.current > 0 ||
        requestedGeneration !== mutationGeneration.current
      ) {
        if (mutationDepth.current > 0) pendingSync.current = true;
        return;
      }
      if (!state.preferencesInitialized) {
        state = await persistAccountPreferences({
          initializeOnly: true,
          travelCostPerKm: travelCostRef.current,
          notifications: notificationsRef.current,
        });
        if (
          mutationDepth.current > 0 ||
          requestedGeneration !== mutationGeneration.current
        ) {
          pendingSync.current = true;
          return;
        }
      }
      const revision = Number(state.revision ?? 0);
      if (revision > 0 && revision < latestRevision.current) return;
      applyState(state);
      latestRevision.current = Math.max(latestRevision.current, revision);
      performanceMark("account-state-end");
      performanceMeasure("account-reconciliation", "account-state-start", "account-state-end");
    } catch {
      // Offline/temporary backend failures keep the cached UI usable.
    } finally {
      syncing.current = false;
      if (pendingSync.current && mutationDepth.current === 0) {
        pendingSync.current = false;
        scheduleSyncRef.current(40);
      }
    }
  }, [applyState, store.hydrated]);

  const scheduleSync = useCallback((delay = 40) => {
    pendingSync.current = true;
    if (mutationDepth.current > 0 || syncTimer.current != null) return;
    syncTimer.current = window.setTimeout(() => {
      syncTimer.current = null;
      pendingSync.current = false;
      void sync();
    }, delay);
  }, [sync]);
  scheduleSyncRef.current = scheduleSync;

  useEffect(() => {
    if (!store.hydrated) return;
    const onMutationStart = () => {
      mutationDepth.current += 1;
      mutationGeneration.current += 1;
    };
    const onMutationEnd = () => {
      mutationDepth.current = Math.max(0, mutationDepth.current - 1);
      if (mutationDepth.current === 0 && pendingSync.current) scheduleSync(40);
    };
    const onSyncRequest = () => scheduleSync(40);
    window.addEventListener(ACCOUNT_MUTATION_START_EVENT, onMutationStart);
    window.addEventListener(ACCOUNT_MUTATION_END_EVENT, onMutationEnd);
    window.addEventListener(ACCOUNT_SYNC_REQUEST_EVENT, onSyncRequest);
    return () => {
      window.removeEventListener(ACCOUNT_MUTATION_START_EVENT, onMutationStart);
      window.removeEventListener(ACCOUNT_MUTATION_END_EVENT, onMutationEnd);
      window.removeEventListener(ACCOUNT_SYNC_REQUEST_EVENT, onSyncRequest);
    };
  }, [store.hydrated, scheduleSync]);

  useEffect(() => {
    if (!store.hydrated) return;
    scheduleSync(0);

    let events: EventSource | null = null;
    let stopped = false;
    const onReady = (event: Event) => {
      try {
        const revision = Number(JSON.parse((event as MessageEvent<string>).data || "{}")?.revision ?? 0);
        latestRevision.current = Math.max(latestRevision.current, revision);
      } catch { /* initial state request remains authoritative */ }
    };
    if (window.localStorage.getItem(ACCOUNT_PROFILE_STORAGE_KEY)) {
      events = new EventSource("/api/account/events", { withCredentials: true });
      const onRemoteState = (event: Event) => {
        if (stopped) return;
        let revision = 0;
        try {
          revision = Number(JSON.parse((event as MessageEvent<string>).data || "{}")?.revision ?? 0);
        } catch { /* malformed events still trigger a canonical reconciliation */ }
        if (revision > 0 && revision <= latestRevision.current) return;
        if (revision > 0) latestRevision.current = revision;
        notifyFavoritesChanged();
        scheduleSync(0);
      };
      events.addEventListener("ready", onReady);
      events.addEventListener("state", onRemoteState);
      events.addEventListener("favorites", onRemoteState);
      events.onerror = () => { if (!stopped) scheduleSync(500); };
    }

    // Slow integrity safety net only. Focus/resume and online events reconcile immediately.
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") scheduleSync(0);
    }, 120_000);
    const onVisible = () => { if (document.visibilityState === "visible") scheduleSync(0); };
    const onResume = () => scheduleSync(0);
    window.addEventListener("focus", onResume);
    window.addEventListener("online", onResume);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      stopped = true;
      if (events) {
        events.onerror = null;
        events.removeEventListener("ready", onReady);
      }
      events?.close();
      window.clearInterval(interval);
      if (syncTimer.current != null) window.clearTimeout(syncTimer.current);
      window.removeEventListener("focus", onResume);
      window.removeEventListener("online", onResume);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [store.hydrated, scheduleSync]);

  return null;
}

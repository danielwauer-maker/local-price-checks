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
  const favoriteProductsRef = useRef(store.favoriteProducts);
  const locationRef = useRef(store.location);
  const radiusRef = useRef(store.radius);
  const travelCostRef = useRef(store.travelCostPerKm);
  const notificationsRef = useRef(store.notifications);
  const toggleFavoriteRef = useRef(store.toggleFavoriteProduct);
  const setLocationRef = useRef(store.setLocation);
  const setRadiusRef = useRef(store.setRadius);
  const setTravelCostRef = useRef(store.setTravelCostPerKm);
  const setNotificationRef = useRef(store.setNotification);

  useEffect(() => { favoriteProductsRef.current = store.favoriteProducts; }, [store.favoriteProducts]);
  useEffect(() => { locationRef.current = store.location; }, [store.location]);
  useEffect(() => { radiusRef.current = store.radius; }, [store.radius]);
  useEffect(() => { travelCostRef.current = store.travelCostPerKm; }, [store.travelCostPerKm]);
  useEffect(() => { notificationsRef.current = store.notifications; }, [store.notifications]);
  useEffect(() => { toggleFavoriteRef.current = store.toggleFavoriteProduct; }, [store.toggleFavoriteProduct]);
  useEffect(() => { setLocationRef.current = store.setLocation; }, [store.setLocation]);
  useEffect(() => { setRadiusRef.current = store.setRadius; }, [store.setRadius]);
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

    const profile = state.profile;
    if (profile) {
      const nextRadius = Number(profile.radiusKm || 15);
      if (Math.abs(radiusRef.current - nextRadius) > 0.001) {
        setRadiusRef.current(nextRadius);
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
          setLocationRef.current(next);
          locationRef.current = next;
        }
      }
    }

    if (state.favoritePreferences) {
      queryClient.setQueryData(["favorite-preferences"], state.favoritePreferences);
    }
    // These resources are canonical backend views and are safe to refetch on every account event.
    // Favorite markets are not toggled locally here because their legacy API is toggle-based;
    // refetching avoids accidentally reversing a remote change.
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

    let events: EventSource | null = null;
    if (window.localStorage.getItem(ACCOUNT_PROFILE_STORAGE_KEY)) {
      events = new EventSource("/api/account/events", { withCredentials: true });
      const onRemoteState = () => {
        notifyFavoritesChanged();
        void sync();
      };
      events.addEventListener("ready", onRemoteState);
      events.addEventListener("state", onRemoteState);
      events.addEventListener("favorites", onRemoteState);
      events.onerror = () => {
        window.setTimeout(() => void sync(), 250);
      };
    }

    // Closed-beta safety net for suspended iOS/WebKit sessions. Normal active sync is SSE-driven.
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") void sync();
    }, 15_000);
    const onVisible = () => { if (document.visibilityState === "visible") void sync(); };
    window.addEventListener("focus", sync);
    window.addEventListener("online", sync);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      events?.close();
      window.clearInterval(interval);
      window.removeEventListener("focus", sync);
      window.removeEventListener("online", sync);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [store.hydrated, sync]);

  return null;
}

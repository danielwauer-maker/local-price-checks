import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  DEFAULT_LOCATION,
  type DietTag,
  type RegionStatus,
} from "@/data/lokero";
import {
  fetchBootstrap,
  persistBasketClear,
  persistBasketQuantity,
  persistLocation,
  persistMarketToggle,
} from "@/services/lokero-api";
import { persistProductFavorite } from "@/services/lokero-state-api";
import { ACCOUNT_PROFILE_STORAGE_KEY } from "@/services/lokero-account-api";
import { performanceMark, performanceMeasure } from "@/lib/performance";
import {
  addSharedManualItem,
  clearSharedList,
  createShoppingList,
  deleteSharedListItem,
  fetchActiveShoppingList,
  fetchShoppingLists,
  patchSharedListItem,
  putSharedProduct,
  setActiveShoppingList,
  type SharedListMember,
  type SharedListSnapshot,
  type SharedListSummary,
} from "@/services/sharing-api";

type Location = { lat: number; lng: number; label: string };
export type ManualListItem = { id: string; name: string; qty: number };

export type NotificationSettings = {
  priceAlerts: boolean;
  newOffers: boolean;
  regionAvailable: boolean;
  favoriteOffers: boolean;
};

type StoreState = {
  location: Location;
  radius: number;
  list: Record<string, number>;
  manualListItems: ManualListItem[];
  checkedListItems: string[];
  favoriteProducts: string[];
  favoriteMarkets: string[];
  alerts: Record<string, { targetPrice: number; active: boolean }>;
  preferredChains: string[];
  travelCostPerKm: number;
  notifications: NotificationSettings;
  diet: DietTag[];
  regionStatusOverride: RegionStatus | "auto";
  sharingEnabled: boolean;
  shoppingLists: SharedListSummary[];
  activeShoppingListId: string | null;
  activeShoppingListName: string;
  activeShoppingListMembers: SharedListMember[];
  activeShoppingListIsPersonal: boolean;
  sharedItemIds: Record<string, string>;
  sharedRevision: number;
};

const STORAGE_KEY = "lokero.state.v1";
export const manualListKey = (id: string) => `manual:${id}`;

const initialState: StoreState = {
  location: DEFAULT_LOCATION,
  radius: 15,
  list: {},
  manualListItems: [],
  checkedListItems: [],
  favoriteProducts: [],
  favoriteMarkets: [],
  alerts: {},
  preferredChains: ["REWE", "Lidl", "ALDI SÜD", "Netto", "EDEKA"],
  travelCostPerKm: 0.3,
  notifications: { priceAlerts: true, newOffers: true, regionAvailable: true, favoriteOffers: false },
  diet: [],
  regionStatusOverride: "auto",
  sharingEnabled: false,
  shoppingLists: [],
  activeShoppingListId: null,
  activeShoppingListName: "Meine Einkaufsliste",
  activeShoppingListMembers: [],
  activeShoppingListIsPersonal: true,
  sharedItemIds: {},
  sharedRevision: 0,
};

function snapshotState(snapshot: SharedListSnapshot): Partial<StoreState> {
  const list: Record<string, number> = {};
  const manualListItems: ManualListItem[] = [];
  const checkedListItems: string[] = [];
  const sharedItemIds: Record<string, string> = {};
  for (const item of snapshot.items) {
    if (item.productId) {
      list[item.productId] = Number(item.quantity);
      sharedItemIds[item.productId] = item.id;
      if (item.checked) checkedListItems.push(item.productId);
    } else if (item.manualText) {
      manualListItems.push({ id: item.id, name: item.manualText, qty: Number(item.quantity) });
      const key = manualListKey(item.id);
      sharedItemIds[key] = item.id;
      if (item.checked) checkedListItems.push(key);
    }
  }
  return {
    list,
    manualListItems,
    checkedListItems,
    sharedItemIds,
    activeShoppingListId: snapshot.list.id,
    activeShoppingListName: snapshot.list.name,
    activeShoppingListMembers: snapshot.list.members ?? [],
    activeShoppingListIsPersonal: snapshot.list.isPersonal,
    sharedRevision: Number(snapshot.list.revision ?? 0),
  };
}

type StoreContextValue = StoreState & {
  hydrated: boolean;
  backendHydrated: boolean;
  listEntries: Array<{ productId: string; qty: number }>;
  listCount: number;
  refreshShoppingSharing: () => Promise<void>;
  selectShoppingList: (listId: string) => Promise<void>;
  createSharedShoppingList: (name: string) => Promise<SharedListSummary>;
  reconcileAccountState: (value: { location?: Location; radius?: number; favoriteMarkets?: string[] }) => void;
  setLocation: (loc: Location) => void;
  setRadius: (km: number) => void;
  addToList: (productId: string, qty?: number) => void;
  setQty: (productId: string, qty: number) => void;
  addManualListItem: (name: string, qty?: number) => void;
  setManualListQty: (id: string, qty: number) => void;
  removeManualListItem: (id: string) => void;
  clearList: () => void;
  toggleListChecked: (itemKey: string) => void;
  clearCheckedList: () => void;
  toggleFavoriteProduct: (id: string) => void;
  toggleFavoriteMarket: (id: string) => void;
  isFavoriteProduct: (id: string) => boolean;
  setAlert: (productId: string, targetPrice: number, active: boolean) => void;
  removeAlert: (productId: string) => void;
  togglePreferredChain: (chain: string) => void;
  setTravelCostPerKm: (value: number) => void;
  setNotification: (key: keyof NotificationSettings, value: boolean) => void;
  toggleDiet: (tag: DietTag) => void;
  setRegionStatusOverride: (status: RegionStatus | "auto") => void;
};

const Ctx = createContext<StoreContextValue | null>(null);

export function AppStoreProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<StoreState>(initialState);
  const stateRef = useRef<StoreState>(initialState);
  const [hydrated, setHydrated] = useState(false);
  const [backendHydrated, setBackendHydrated] = useState(false);
  const sharedRevisionRef = useRef(0);

  const patch = useCallback((value: Partial<StoreState> | ((current: StoreState) => Partial<StoreState>)) => {
    const current = stateRef.current;
    const next = { ...current, ...(typeof value === "function" ? value(current) : value) };
    stateRef.current = next;
    setState(next);
    return next;
  }, []);

  useEffect(() => { sharedRevisionRef.current = state.sharedRevision; }, [state.sharedRevision]);

  const refreshActiveShoppingList = useCallback(async () => {
    try {
      performanceMark("shopping-snapshot-start");
      const snapshot = await fetchActiveShoppingList();
      patch({ sharingEnabled: true, ...snapshotState(snapshot) });
      performanceMark("shopping-snapshot-end");
      performanceMeasure("shopping-snapshot", "shopping-snapshot-start", "shopping-snapshot-end");
    } catch {
      // Keep cached list state; reconnect/fallback will retry.
    }
  }, [patch]);

  const refreshShoppingSharing = useCallback(async () => {
    const [overviewResult, snapshotResult] = await Promise.allSettled([
      fetchShoppingLists(),
      fetchActiveShoppingList(),
    ]);
    if (overviewResult.status === "fulfilled") {
      const overview = overviewResult.value;
      if (!overview.enabled) {
        patch({ sharingEnabled: false, shoppingLists: [], activeShoppingListId: null, activeShoppingListMembers: [], sharedItemIds: {}, sharedRevision: 0 });
        return;
      }
      if (snapshotResult.status === "fulfilled") {
        patch({ sharingEnabled: true, shoppingLists: overview.lists, ...snapshotState(snapshotResult.value) });
      } else {
        patch({ sharingEnabled: true, shoppingLists: overview.lists });
      }
    } else if (snapshotResult.status === "fulfilled") {
      patch({ sharingEnabled: true, ...snapshotState(snapshotResult.value) });
    }
  }, [patch]);

  useEffect(() => {
    performanceMark("store-hydration-start");
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const stored = JSON.parse(raw) as Partial<StoreState>;
        patch({ ...initialState, ...stored, sharingEnabled: false, shoppingLists: [], activeShoppingListId: null, activeShoppingListMembers: [], sharedItemIds: {}, sharedRevision: 0 });
      }
    } catch { /* ignore */ }
    setHydrated(true);
    performanceMark("store-hydration-end");
    performanceMeasure("store-hydration", "store-hydration-start", "store-hydration-end");

    performanceMark("bootstrap-start");
    void fetchBootstrap().then((bootstrap) => {
      if (!bootstrap) return;
      patch((current) => {
        const nextList = bootstrap.basket ?? current.list;
        const validManualKeys = new Set(current.manualListItems.map((item) => manualListKey(item.id)));
        return {
          ...current,
          location: bootstrap.location ?? current.location,
          radius: Number(bootstrap.radius ?? current.radius),
          list: current.sharingEnabled ? current.list : nextList,
          checkedListItems: current.sharingEnabled ? current.checkedListItems : current.checkedListItems.filter((id) => Number(nextList[id] ?? 0) > 0 || validManualKeys.has(id)),
          favoriteMarkets: bootstrap.favorites ?? bootstrap.selected ?? current.favoriteMarkets,
        };
      });
      setBackendHydrated(true);
      performanceMark("bootstrap-end");
      performanceMeasure("bootstrap", "bootstrap-start", "bootstrap-end");
    });
  }, [patch]);

  useEffect(() => {
    if (!hydrated) return;
    const { sharingEnabled: _sharingEnabled, shoppingLists: _shoppingLists, activeShoppingListId: _activeShoppingListId, activeShoppingListMembers: _activeShoppingListMembers, sharedItemIds: _sharedItemIds, sharedRevision: _sharedRevision, ...persistable } = state;
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(persistable));
  }, [state, hydrated]);

  useEffect(() => {
    if (!hydrated) return;
    let cancelled = false;
    const initialize = async () => {
      try {
        const linked = Boolean(window.localStorage.getItem(ACCOUNT_PROFILE_STORAGE_KEY));
        const overviewPromise = fetchShoppingLists();
        const snapshotPromise = linked ? fetchActiveShoppingList() : null;
        const overview = await overviewPromise;
        if (cancelled || !overview.enabled) {
          if (!cancelled) patch({ sharingEnabled: false, shoppingLists: [] });
          return;
        }
        let snapshot = await (snapshotPromise ?? fetchActiveShoppingList());
        if (cancelled) return;
        const current = stateRef.current;
        const serverManual = snapshot.items.filter((item) => item.manualText);
        if (snapshot.list.isPersonal && serverManual.length === 0 && current.manualListItems.length > 0) {
          const checkedNames = new Set(current.manualListItems.filter((item) => current.checkedListItems.includes(manualListKey(item.id))).map((item) => item.name.trim().toLocaleLowerCase("de-DE")));
          for (const item of current.manualListItems) snapshot = await addSharedManualItem(snapshot.list.id, item.name, item.qty);
          for (const item of snapshot.items) {
            if (item.manualText && !item.checked && checkedNames.has(item.manualText.trim().toLocaleLowerCase("de-DE"))) snapshot = await patchSharedListItem(snapshot.list.id, item.id, { checked: true });
          }
        }
        for (const item of snapshot.items) {
          if (item.productId && !item.checked && current.checkedListItems.includes(item.productId)) snapshot = await patchSharedListItem(snapshot.list.id, item.id, { checked: true });
        }
        if (!cancelled) patch({ sharingEnabled: true, shoppingLists: overview.lists, ...snapshotState(snapshot) });
      } catch {
        if (!cancelled) patch({ sharingEnabled: false });
      }
    };
    void initialize();
    return () => { cancelled = true; };
  }, [hydrated, patch]);

  useEffect(() => {
    if (!state.sharingEnabled || !state.activeShoppingListId || typeof EventSource === "undefined") return;
    const listId = state.activeShoppingListId;
    let source: EventSource | null = null;
    let fallback: number | null = null;
    let reconnect: number | null = null;
    let reconnectDelay = 1_000;
    let stopped = false;

    const stopFallback = () => {
      if (fallback != null) window.clearInterval(fallback);
      fallback = null;
    };
    const startFallback = () => {
      if (fallback != null) return;
      void refreshActiveShoppingList();
      fallback = window.setInterval(() => {
        if (document.visibilityState === "visible") void refreshActiveShoppingList();
      }, 120_000);
    };
    const scheduleReconnect = () => {
      if (stopped || reconnect != null || !navigator.onLine) return;
      reconnect = window.setTimeout(() => {
        reconnect = null;
        connect();
      }, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, 10_000);
    };
    const onRevision = (event: MessageEvent<string>) => {
      if (stopped) return;
      try {
        const revision = Number((JSON.parse(event.data) as { revision?: number }).revision ?? 0);
        if (revision && revision === sharedRevisionRef.current) return;
      } catch { /* refresh below */ }
      void refreshActiveShoppingList();
    };
    const onAccessRevoked = () => { if (!stopped) void refreshShoppingSharing(); };
    const connect = () => {
      if (stopped || source || !navigator.onLine) return;
      const next = new EventSource(`/api/sharing/lists/${encodeURIComponent(listId)}/events`);
      source = next;
      next.addEventListener("revision", onRevision as EventListener);
      next.addEventListener("access_revoked", onAccessRevoked);
      next.onopen = () => {
        if (stopped || source !== next) {
          next.close();
          return;
        }
        reconnectDelay = 1_000;
        stopFallback();
      };
      next.onerror = () => {
        if (stopped || source !== next) {
          next.close();
          return;
        }
        source = null;
        next.close();
        startFallback();
        scheduleReconnect();
      };
    };
    const resume = () => {
      if (document.visibilityState !== "visible" || !navigator.onLine) return;
      void refreshActiveShoppingList();
      if (!source) connect();
    };

    connect();
    window.addEventListener("online", resume);
    window.addEventListener("focus", resume);
    document.addEventListener("visibilitychange", resume);
    return () => {
      stopped = true;
      stopFallback();
      if (reconnect != null) window.clearTimeout(reconnect);
      if (source) {
        source.onopen = null;
        source.onerror = null;
        source.removeEventListener("revision", onRevision as EventListener);
        source.removeEventListener("access_revoked", onAccessRevoked);
        source.close();
      }
      window.removeEventListener("online", resume);
      window.removeEventListener("focus", resume);
      document.removeEventListener("visibilitychange", resume);
    };
  }, [state.sharingEnabled, state.activeShoppingListId, refreshActiveShoppingList, refreshShoppingSharing]);

  useEffect(() => {
    if (!hydrated) return;
    document.documentElement.dataset.appReady = "true";
    return () => {
      delete document.documentElement.dataset.appReady;
    };
  }, [hydrated]);

  const value = useMemo<StoreContextValue>(() => {
    const listEntries = Object.entries(state.list).filter(([, qty]) => qty > 0).map(([productId, qty]) => ({ productId, qty }));
    const applyShared = (promise: Promise<SharedListSnapshot>) => { void promise.then((snapshot) => patch(snapshotState(snapshot))).catch(() => void refreshShoppingSharing()); };
    return {
      ...state,
      hydrated,
      backendHydrated,
      listEntries,
      listCount: listEntries.reduce((sum, entry) => sum + entry.qty, 0),
      refreshShoppingSharing,
      selectShoppingList: async (listId) => {
        const snapshot = await setActiveShoppingList(listId);
        const overview = await fetchShoppingLists();
        patch({ sharingEnabled: true, shoppingLists: overview.lists, ...snapshotState(snapshot) });
      },
      createSharedShoppingList: async (name) => {
        const created = await createShoppingList(name);
        const [snapshot, overview] = await Promise.all([
          fetchActiveShoppingList(),
          fetchShoppingLists(),
        ]);
        patch({ sharingEnabled: true, shoppingLists: overview.lists, ...snapshotState(snapshot) });
        return created;
      },
      reconcileAccountState: (value) => patch((current) => ({
        location: value.location ?? current.location,
        radius: value.radius ?? current.radius,
        favoriteMarkets: value.favoriteMarkets ? [...value.favoriteMarkets] : current.favoriteMarkets,
      })),
      setLocation: (location) => { const next = patch({ location }); void persistLocation({ ...location, radius: next.radius }); },
      setRadius: (radius) => { const next = patch({ radius }); void persistLocation({ ...next.location, radius }); },
      addToList: (productId, qty = 1) => {
        const next = patch((current) => ({ list: { ...current.list, [productId]: (current.list[productId] ?? 0) + qty }, checkedListItems: current.checkedListItems.filter((id) => id !== productId) }));
        const nextQty = next.list[productId] ?? 0;
        if (next.sharingEnabled && next.activeShoppingListId) applyShared(putSharedProduct(next.activeShoppingListId, productId, nextQty));
        else void persistBasketQuantity(productId, nextQty);
      },
      setQty: (productId, qty) => {
        const next = patch((current) => {
          const list = { ...current.list };
          if (qty <= 0) delete list[productId]; else list[productId] = qty;
          return { list, checkedListItems: qty <= 0 ? current.checkedListItems.filter((id) => id !== productId) : current.checkedListItems };
        });
        if (next.sharingEnabled && next.activeShoppingListId) applyShared(putSharedProduct(next.activeShoppingListId, productId, Math.max(0, qty)));
        else void persistBasketQuantity(productId, Math.max(0, qty));
      },
      addManualListItem: (name, qty = 1) => {
        const cleanName = name.trim().replace(/\s+/g, " ");
        if (!cleanName) return;
        if (state.sharingEnabled && state.activeShoppingListId) { applyShared(addSharedManualItem(state.activeShoppingListId, cleanName, qty)); return; }
        patch((current) => {
          const existing = current.manualListItems.find((item) => item.name.toLocaleLowerCase("de-DE") === cleanName.toLocaleLowerCase("de-DE"));
          if (existing) return { manualListItems: current.manualListItems.map((item) => item.id === existing.id ? { ...item, qty: item.qty + qty } : item), checkedListItems: current.checkedListItems.filter((key) => key !== manualListKey(existing.id)) };
          const id = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
          return { manualListItems: [...current.manualListItems, { id, name: cleanName, qty: Math.max(1, qty) }] };
        });
      },
      setManualListQty: (id, qty) => {
        patch((current) => ({ manualListItems: qty <= 0 ? current.manualListItems.filter((item) => item.id !== id) : current.manualListItems.map((item) => item.id === id ? { ...item, qty } : item), checkedListItems: qty <= 0 ? current.checkedListItems.filter((key) => key !== manualListKey(id)) : current.checkedListItems }));
        if (state.sharingEnabled && state.activeShoppingListId) { if (qty <= 0) applyShared(deleteSharedListItem(state.activeShoppingListId, id)); else applyShared(patchSharedListItem(state.activeShoppingListId, id, { quantity: qty })); }
      },
      removeManualListItem: (id) => {
        patch((current) => ({ manualListItems: current.manualListItems.filter((item) => item.id !== id), checkedListItems: current.checkedListItems.filter((key) => key !== manualListKey(id)) }));
        if (state.sharingEnabled && state.activeShoppingListId) applyShared(deleteSharedListItem(state.activeShoppingListId, id));
      },
      clearList: () => {
        patch({ list: {}, manualListItems: [], checkedListItems: [], sharedItemIds: {} });
        if (state.sharingEnabled && state.activeShoppingListId) applyShared(clearSharedList(state.activeShoppingListId)); else void persistBasketClear();
      },
      toggleListChecked: (itemKey) => {
        const nextChecked = !state.checkedListItems.includes(itemKey);
        patch((current) => ({ checkedListItems: nextChecked ? [...current.checkedListItems, itemKey] : current.checkedListItems.filter((id) => id !== itemKey) }));
        if (state.sharingEnabled && state.activeShoppingListId) { const itemId = state.sharedItemIds[itemKey]; if (itemId) applyShared(patchSharedListItem(state.activeShoppingListId, itemId, { checked: nextChecked })); }
      },
      clearCheckedList: () => patch({ checkedListItems: [] }),
      toggleFavoriteProduct: (id) => {
        const next = patch((current) => {
          const favorite = !current.favoriteProducts.includes(id);
          return { favoriteProducts: favorite ? [...current.favoriteProducts, id] : current.favoriteProducts.filter((productId) => productId !== id) };
        });
        const favorite = next.favoriteProducts.includes(id);
        void persistProductFavorite(id, favorite);
      },
      toggleFavoriteMarket: (id) => { patch((current) => ({ favoriteMarkets: current.favoriteMarkets.includes(id) ? current.favoriteMarkets.filter((marketId) => marketId !== id) : [...current.favoriteMarkets, id] })); void persistMarketToggle(id); },
      isFavoriteProduct: (id) => state.favoriteProducts.includes(id),
      setAlert: (productId, targetPrice, active) => patch((current) => ({ alerts: { ...current.alerts, [productId]: { targetPrice, active } } })),
      removeAlert: (productId) => patch((current) => { const next = { ...current.alerts }; delete next[productId]; return { alerts: next }; }),
      togglePreferredChain: (chain) => patch((current) => ({ preferredChains: current.preferredChains.includes(chain) ? current.preferredChains.filter((item) => item !== chain) : [...current.preferredChains, chain] })),
      setTravelCostPerKm: (travelCostPerKm) => patch({ travelCostPerKm }),
      setNotification: (key, value) => patch((current) => ({ notifications: { ...current.notifications, [key]: value } })),
      toggleDiet: (tag) => patch((current) => ({ diet: current.diet.includes(tag) ? current.diet.filter((item) => item !== tag) : [...current.diet, tag] })),
      setRegionStatusOverride: (regionStatusOverride) => patch({ regionStatusOverride }),
    };
  }, [state, hydrated, backendHydrated, patch, refreshShoppingSharing]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useStore must be used within AppStoreProvider");
  return ctx;
}

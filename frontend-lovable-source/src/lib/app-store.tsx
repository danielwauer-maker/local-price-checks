import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  DEFAULT_LIST,
  DEFAULT_LOCATION,
  FAVORITE_MARKET_IDS,
  FAVORITE_PRODUCTS,
  PRICE_ALERTS,
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
  /** Nur Preview: erlaubt das Durchspielen der drei Regionszustände. */
  regionStatusOverride: RegionStatus | "auto";
};

const STORAGE_KEY = "lokero.state.v1";
export const manualListKey = (id: string) => `manual:${id}`;

const initialState: StoreState = {
  location: DEFAULT_LOCATION,
  radius: 15,
  list: Object.fromEntries(DEFAULT_LIST.map((i) => [i.productId, i.qty])),
  manualListItems: [],
  checkedListItems: [],
  favoriteProducts: FAVORITE_PRODUCTS.map((f) => f.productId),
  favoriteMarkets: FAVORITE_MARKET_IDS,
  alerts: Object.fromEntries(
    PRICE_ALERTS.map((a) => [a.productId, { targetPrice: a.targetPrice, active: a.active }]),
  ),
  preferredChains: ["REWE", "Lidl", "ALDI SÜD", "Netto", "EDEKA"],
  travelCostPerKm: 0.3,
  notifications: {
    priceAlerts: true,
    newOffers: true,
    regionAvailable: true,
    favoriteOffers: false,
  },
  diet: [],
  regionStatusOverride: "auto",
};

type StoreContextValue = StoreState & {
  hydrated: boolean;
  backendHydrated: boolean;
  listEntries: Array<{ productId: string; qty: number }>;
  listCount: number;
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
  const [hydrated, setHydrated] = useState(false);
  const [backendHydrated, setBackendHydrated] = useState(false);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) setState({ ...initialState, ...(JSON.parse(raw) as StoreState) });
    } catch {
      /* ignore */
    }
    setHydrated(true);

    void fetchBootstrap().then((bootstrap) => {
      if (!bootstrap) return;
      setState((current) => {
        const nextList = bootstrap.basket ?? current.list;
        const validManualKeys = new Set(current.manualListItems.map((item) => manualListKey(item.id)));
        return {
          ...current,
          location: bootstrap.location ?? current.location,
          radius: Number(bootstrap.radius ?? current.radius),
          list: nextList,
          checkedListItems: current.checkedListItems.filter(
            (id) => Number(nextList[id] ?? 0) > 0 || validManualKeys.has(id),
          ),
          favoriteMarkets: bootstrap.favorites ?? bootstrap.selected ?? current.favoriteMarkets,
        };
      });
      setBackendHydrated(true);
    });
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }, [state, hydrated]);

  const patch = useCallback(
    (p: Partial<StoreState> | ((s: StoreState) => Partial<StoreState>)) =>
      setState((s) => ({ ...s, ...(typeof p === "function" ? p(s) : p) })),
    [],
  );

  const value = useMemo<StoreContextValue>(() => {
    const listEntries = Object.entries(state.list)
      .filter(([, qty]) => qty > 0)
      .map(([productId, qty]) => ({ productId, qty }));

    return {
      ...state,
      hydrated,
      backendHydrated,
      listEntries,
      listCount: listEntries.reduce((s, e) => s + e.qty, 0),
      setLocation: (location) => {
        patch({ location });
        void persistLocation({ ...location, radius: state.radius });
      },
      setRadius: (radius) => {
        patch({ radius });
        void persistLocation({ ...state.location, radius });
      },
      addToList: (productId, qty = 1) => {
        const nextQty = (state.list[productId] ?? 0) + qty;
        patch((s) => ({
          list: { ...s.list, [productId]: nextQty },
          checkedListItems: s.checkedListItems.filter((id) => id !== productId),
        }));
        void persistBasketQuantity(productId, nextQty);
      },
      setQty: (productId, qty) => {
        patch((s) => {
          const next = { ...s.list };
          if (qty <= 0) delete next[productId];
          else next[productId] = qty;
          return {
            list: next,
            checkedListItems: qty <= 0 ? s.checkedListItems.filter((id) => id !== productId) : s.checkedListItems,
          };
        });
        void persistBasketQuantity(productId, Math.max(0, qty));
      },
      addManualListItem: (name, qty = 1) => {
        const cleanName = name.trim().replace(/\s+/g, " ");
        if (!cleanName) return;
        patch((s) => {
          const existing = s.manualListItems.find((item) => item.name.toLocaleLowerCase("de-DE") === cleanName.toLocaleLowerCase("de-DE"));
          if (existing) {
            return {
              manualListItems: s.manualListItems.map((item) => item.id === existing.id ? { ...item, qty: item.qty + qty } : item),
              checkedListItems: s.checkedListItems.filter((key) => key !== manualListKey(existing.id)),
            };
          }
          const id = typeof crypto !== "undefined" && "randomUUID" in crypto
            ? crypto.randomUUID()
            : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
          return { manualListItems: [...s.manualListItems, { id, name: cleanName, qty: Math.max(1, qty) }] };
        });
      },
      setManualListQty: (id, qty) =>
        patch((s) => ({
          manualListItems: qty <= 0
            ? s.manualListItems.filter((item) => item.id !== id)
            : s.manualListItems.map((item) => item.id === id ? { ...item, qty } : item),
          checkedListItems: qty <= 0
            ? s.checkedListItems.filter((key) => key !== manualListKey(id))
            : s.checkedListItems,
        })),
      removeManualListItem: (id) =>
        patch((s) => ({
          manualListItems: s.manualListItems.filter((item) => item.id !== id),
          checkedListItems: s.checkedListItems.filter((key) => key !== manualListKey(id)),
        })),
      clearList: () => {
        patch({ list: {}, manualListItems: [], checkedListItems: [] });
        void persistBasketClear();
      },
      toggleListChecked: (itemKey) =>
        patch((s) => ({
          checkedListItems: s.checkedListItems.includes(itemKey)
            ? s.checkedListItems.filter((id) => id !== itemKey)
            : [...s.checkedListItems, itemKey],
        })),
      clearCheckedList: () => patch({ checkedListItems: [] }),
      toggleFavoriteProduct: (id) => {
        const favorite = !state.favoriteProducts.includes(id);
        patch((s) => ({
          favoriteProducts: favorite
            ? [...s.favoriteProducts, id]
            : s.favoriteProducts.filter((x) => x !== id),
        }));
        void persistProductFavorite(id, favorite);
      },
      toggleFavoriteMarket: (id) => {
        patch((s) => ({
          favoriteMarkets: s.favoriteMarkets.includes(id)
            ? s.favoriteMarkets.filter((x) => x !== id)
            : [...s.favoriteMarkets, id],
        }));
        void persistMarketToggle(id);
      },
      isFavoriteProduct: (id) => state.favoriteProducts.includes(id),
      setAlert: (productId, targetPrice, active) =>
        patch((s) => ({ alerts: { ...s.alerts, [productId]: { targetPrice, active } } })),
      removeAlert: (productId) =>
        patch((s) => {
          const next = { ...s.alerts };
          delete next[productId];
          return { alerts: next };
        }),
      togglePreferredChain: (chain) =>
        patch((s) => ({
          preferredChains: s.preferredChains.includes(chain)
            ? s.preferredChains.filter((c) => c !== chain)
            : [...s.preferredChains, chain],
        })),
      setTravelCostPerKm: (travelCostPerKm) => patch({ travelCostPerKm }),
      setNotification: (key, val) =>
        patch((s) => ({ notifications: { ...s.notifications, [key]: val } })),
      toggleDiet: (tag) =>
        patch((s) => ({
          diet: s.diet.includes(tag) ? s.diet.filter((t) => t !== tag) : [...s.diet, tag],
        })),
      setRegionStatusOverride: (regionStatusOverride) => patch({ regionStatusOverride }),
    };
  }, [state, hydrated, backendHydrated, patch]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useStore must be used within AppStoreProvider");
  return ctx;
}

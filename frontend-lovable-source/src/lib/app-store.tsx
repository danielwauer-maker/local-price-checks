import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { DEFAULT_LOCATION, MARKETS, PRODUCTS, PRICES, distanceKm, type Market, type Price, type Product } from "@/data/demo";
import { withDeviceIdentity } from "./device-identity";

type Location = { lat: number; lng: number; label: string };
type Profile = { displayName: string; postalCode: string; city: string };

type StoreState = {
  location: Location;
  radius: number;
  maxStops: number;
  selected: string[];
  favorites: string[];
  productFavorites: string[];
  checked: string[];
  profile: Profile;
  basket: Record<string, number>;
};

type BootstrapPayload = Omit<StoreState, "productFavorites" | "checked" | "profile"> & {
  markets: Market[];
  products: Product[];
  prices: Price[];
  activeSelected?: string[];
};

type UxBootstrapPayload = {
  profile: Profile;
  productFavorites: string[];
  checked: string[];
};

type StoreTogglePayload = {
  selected: boolean;
  selectedIds: string[];
  activeSelectedIds: string[];
  prices: Price[];
  refreshStarted: boolean;
};

type StoreOffersPayload = {
  marketId: string;
  status: string;
  prices: Price[];
};

const initialState: StoreState = {
  location: DEFAULT_LOCATION,
  radius: 15,
  maxStops: 2,
  selected: [],
  favorites: [],
  productFavorites: [],
  checked: [],
  profile: { displayName: "", postalCode: "", city: "" },
  basket: {},
};

type StoreContext = StoreState & {
  hydrated: boolean;
  marketsInRadius: Array<(typeof MARKETS)[number] & { distance: number }>;
  favoriteMarketsOutsideRadius: Array<(typeof MARKETS)[number] & { distance: number }>;
  refreshingMarketIds: string[];
  basketEntries: Array<{ productId: string; qty: number }>;
  basketCount: number;
  setLocation: (loc: Location) => void;
  setRadius: (km: number) => void;
  setMaxStops: (n: number) => void;
  toggleSelected: (id: string) => void;
  toggleFavorite: (id: string) => void;
  toggleProductFavorite: (id: string) => void;
  toggleChecked: (id: string) => void;
  updateProfile: (profile: Profile) => Promise<void>;
  addToBasket: (productId: string, qty?: number) => void;
  toggleBasket: (productId: string) => void;
  setQty: (productId: string, qty: number) => void;
  clearBasket: () => void;
};

const Ctx = createContext<StoreContext | null>(null);

function api(path: string, init?: RequestInit) {
  return fetch(path, {
    ...init,
    credentials: init?.credentials ?? "include",
    headers: withDeviceIdentity({ "content-type": "application/json", ...(init?.headers ?? {}) }),
  });
}

function replaceMarketPrices(marketId: string, prices: Price[]) {
  const keep = PRICES.filter((price) => price.marketId !== marketId);
  PRICES.splice(0, PRICES.length, ...keep, ...prices);
}

export function AppStoreProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<StoreState>(initialState);
  const [hydrated, setHydrated] = useState(false);
  const [refreshingMarketIds, setRefreshingMarketIds] = useState<string[]>([]);

  const patch = useCallback(
    (p: Partial<StoreState> | ((s: StoreState) => Partial<StoreState>)) =>
      setState((s) => ({ ...s, ...(typeof p === "function" ? p(s) : p) })),
    [],
  );

  const applyBootstrap = useCallback((payload: BootstrapPayload) => {
    MARKETS.splice(0, MARKETS.length, ...payload.markets);
    PRODUCTS.splice(0, PRODUCTS.length, ...payload.products);
    PRICES.splice(0, PRICES.length, ...payload.prices);
    patch((s) => ({
      location: payload.location,
      radius: payload.radius,
      selected: payload.selected,
      favorites: payload.favorites,
      basket: payload.basket,
      maxStops: s.maxStops,
    }));
  }, [patch]);

  const reloadBootstrap = useCallback(async () => {
    const response = await api("/api/bootstrap");
    if (!response.ok) throw new Error(`bootstrap ${response.status}`);
    const payload = await response.json() as BootstrapPayload;
    applyBootstrap(payload);
    return payload;
  }, [applyBootstrap]);

  const pollStoreOffers = useCallback((id: string, attempt = 0) => {
    const delay = attempt === 0 ? 2500 : Math.min(4000 + attempt * 1500, 9000);
    window.setTimeout(async () => {
      try {
        const response = await api(`/api/stores/${id}/offers`);
        if (!response.ok) throw new Error(`store offers ${response.status}`);
        const payload = await response.json() as StoreOffersPayload;
        replaceMarketPrices(id, payload.prices);
        patch((s) => ({ ...s }));
        const done = ["success", "no_offers", "failed"].includes(payload.status) && attempt >= 1;
        if (done || attempt >= 4) {
          setRefreshingMarketIds((ids) => ids.filter((x) => x !== id));
          return;
        }
        pollStoreOffers(id, attempt + 1);
      } catch {
        if (attempt >= 4) {
          setRefreshingMarketIds((ids) => ids.filter((x) => x !== id));
          return;
        }
        pollStoreOffers(id, attempt + 1);
      }
    }, delay);
  }, [patch]);

  useEffect(() => {
    let live = true;
    Promise.all([
      api("/api/bootstrap").then((r) => {
        if (!r.ok) throw new Error(`bootstrap ${r.status}`);
        return r.json() as Promise<BootstrapPayload>;
      }),
      api("/api/ux/bootstrap").then((r) => {
        if (!r.ok) throw new Error(`ux bootstrap ${r.status}`);
        return r.json() as Promise<UxBootstrapPayload>;
      }),
    ])
      .then(([payload, ux]) => {
        if (!live) return;
        MARKETS.splice(0, MARKETS.length, ...payload.markets);
        PRODUCTS.splice(0, PRODUCTS.length, ...payload.products);
        PRICES.splice(0, PRICES.length, ...payload.prices);
        setState({
          location: payload.location,
          radius: payload.radius,
          maxStops: 2,
          selected: payload.selected,
          favorites: payload.favorites,
          productFavorites: ux.productFavorites,
          checked: ux.checked,
          profile: ux.profile,
          basket: payload.basket,
        });
      })
      .catch((error) => console.error("LocalPrices bootstrap failed", error))
      .finally(() => live && setHydrated(true));
    return () => {
      live = false;
    };
  }, []);

  const value = useMemo<StoreContext>(() => {
    const withDistance = MARKETS.map((m) => ({ ...m, distance: distanceKm(state.location, m) }));
    const marketsInRadius = withDistance
      .filter((m) => m.distance <= state.radius)
      .sort((a, b) => a.distance - b.distance);
    const favoriteMarketsOutsideRadius = withDistance
      .filter((m) => state.selected.includes(m.id) && m.distance > state.radius)
      .sort((a, b) => a.distance - b.distance);

    const basketEntries = Object.entries(state.basket)
      .filter(([, qty]) => qty > 0)
      .map(([productId, qty]) => ({ productId, qty }));

    const activeBasketCount = basketEntries.filter((entry) => !state.checked.includes(entry.productId)).length;

    return {
      ...state,
      hydrated,
      marketsInRadius,
      favoriteMarketsOutsideRadius,
      refreshingMarketIds,
      basketEntries,
      basketCount: activeBasketCount,
      setLocation: (location) => {
        patch({ location });
        void api("/api/location", { method: "PUT", body: JSON.stringify({ ...location, radius: state.radius }) })
          .then((r) => r.ok ? reloadBootstrap() : Promise.reject(new Error(`location ${r.status}`)))
          .catch((error) => console.error("Location refresh failed", error));
      },
      setRadius: (radius) => {
        patch({ radius });
        void api("/api/location", { method: "PUT", body: JSON.stringify({ ...state.location, radius }) })
          .then((r) => r.ok ? reloadBootstrap() : Promise.reject(new Error(`radius ${r.status}`)))
          .catch((error) => console.error("Radius refresh failed", error));
      },
      setMaxStops: (maxStops) => patch({ maxStops }),
      toggleSelected: (id) => {
        const adding = !state.selected.includes(id);
        patch((s) => ({
          selected: adding ? [...s.selected, id] : s.selected.filter((x) => x !== id),
          favorites: adding ? [...s.favorites, id] : s.favorites.filter((x) => x !== id),
        }));
        void api(`/api/stores/${id}/toggle`, { method: "POST" })
          .then(async (response) => {
            if (!response.ok) throw new Error(`store toggle ${response.status}`);
            const result = await response.json() as StoreTogglePayload;
            patch({ selected: result.selectedIds, favorites: result.selectedIds });
            if (result.selected) {
              replaceMarketPrices(id, result.prices);
              patch((s) => ({ ...s }));
              if (result.refreshStarted) {
                setRefreshingMarketIds((ids) => ids.includes(id) ? ids : [...ids, id]);
                pollStoreOffers(id);
              }
            } else {
              replaceMarketPrices(id, []);
              setRefreshingMarketIds((ids) => ids.filter((x) => x !== id));
              patch((s) => ({ ...s }));
            }
          })
          .catch((error) => {
            console.error("Store toggle failed", error);
            patch((s) => ({
              selected: adding ? s.selected.filter((x) => x !== id) : [...s.selected, id],
              favorites: adding ? s.favorites.filter((x) => x !== id) : [...s.favorites, id],
            }));
          });
      },
      toggleFavorite: (id) => patch((s) => ({ favorites: s.favorites.includes(id) ? s.favorites.filter((x) => x !== id) : [...s.favorites, id] })),
      toggleProductFavorite: (id) => {
        patch((s) => ({ productFavorites: s.productFavorites.includes(id) ? s.productFavorites.filter((x) => x !== id) : [...s.productFavorites, id] }));
        void api(`/api/ux/favorites/${id}/toggle`, { method: "POST" });
      },
      toggleChecked: (id) => {
        const next = !state.checked.includes(id);
        patch((s) => ({ checked: next ? [...s.checked, id] : s.checked.filter((x) => x !== id) }));
        void api(`/api/ux/checked/${id}`, { method: "PUT", body: JSON.stringify({ checked: next }) });
      },
      updateProfile: async (profile) => {
        const response = await api("/api/ux/profile", { method: "PUT", body: JSON.stringify({ display_name: profile.displayName, postal_code: profile.postalCode, city: profile.city }) });
        if (!response.ok) throw new Error(`profile ${response.status}`);
        const result = await response.json() as { label?: string; lat?: number; lng?: number };
        patch((s) => ({
          profile,
          location: result.lat != null && result.lng != null
            ? { lat: result.lat, lng: result.lng, label: result.label || `${profile.postalCode} ${profile.city}`.trim() }
            : s.location,
        }));
        await reloadBootstrap();
      },
      addToBasket: (productId, qty = 1) => {
        const nextQty = (state.basket[productId] ?? 0) + qty;
        patch((s) => ({ basket: { ...s.basket, [productId]: nextQty }, checked: s.checked.filter((x) => x !== productId) }));
        void api(`/api/basket/${productId}`, { method: "PUT", body: JSON.stringify({ quantity: nextQty }) });
        void api(`/api/ux/checked/${productId}`, { method: "PUT", body: JSON.stringify({ checked: false }) });
      },
      toggleBasket: (productId) => {
        const inBasket = (state.basket[productId] ?? 0) > 0;
        const nextQty = inBasket ? 0 : 1;
        patch((s) => {
          const next = { ...s.basket };
          if (inBasket) delete next[productId]; else next[productId] = 1;
          return { basket: next, checked: s.checked.filter((x) => x !== productId) };
        });
        void api(`/api/basket/${productId}`, { method: "PUT", body: JSON.stringify({ quantity: nextQty }) });
        if (inBasket) {
          void api(`/api/ux/checked/${productId}`, { method: "PUT", body: JSON.stringify({ checked: false }) });
        }
      },
      setQty: (productId, qty) => {
        const safeQty = Math.max(0, qty);
        patch((s) => {
          const next = { ...s.basket };
          if (safeQty <= 0) delete next[productId]; else next[productId] = safeQty;
          return { basket: next, checked: safeQty <= 0 ? s.checked.filter((x) => x !== productId) : s.checked };
        });
        void api(`/api/basket/${productId}`, { method: "PUT", body: JSON.stringify({ quantity: safeQty }) });
      },
      clearBasket: () => {
        patch({ basket: {}, checked: [] });
        void api("/api/basket", { method: "DELETE" });
        void api("/api/ux/checked", { method: "DELETE" });
      },
    };
  }, [state, hydrated, patch, reloadBootstrap, pollStoreOffers, refreshingMarketIds]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useStore must be used within AppStoreProvider");
  return ctx;
}

export function useActiveMarketIds() {
  const { selected, marketsInRadius } = useStore();
  return useMemo(() => {
    const releasedInRadius = marketsInRadius
      .filter((market) => (market as Market & { verified?: boolean }).verified !== false)
      .map((market) => market.id);
    return selected.filter((id) => releasedInRadius.includes(id));
  }, [selected, marketsInRadius]);
}

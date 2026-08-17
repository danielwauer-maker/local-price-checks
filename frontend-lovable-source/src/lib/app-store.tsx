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

type Location = { lat: number; lng: number; label: string };

type StoreState = {
  location: Location;
  radius: number;
  maxStops: number;
  selected: string[];
  favorites: string[];
  basket: Record<string, number>;
};

type BootstrapPayload = StoreState & {
  markets: Market[];
  products: Product[];
  prices: Price[];
};

const initialState: StoreState = {
  location: DEFAULT_LOCATION,
  radius: 15,
  maxStops: 2,
  selected: [],
  favorites: [],
  basket: {},
};

type StoreContext = StoreState & {
  hydrated: boolean;
  marketsInRadius: Array<(typeof MARKETS)[number] & { distance: number }>;
  basketEntries: Array<{ productId: string; qty: number }>;
  basketCount: number;
  setLocation: (loc: Location) => void;
  setRadius: (km: number) => void;
  setMaxStops: (n: number) => void;
  toggleSelected: (id: string) => void;
  toggleFavorite: (id: string) => void;
  addToBasket: (productId: string, qty?: number) => void;
  setQty: (productId: string, qty: number) => void;
  clearBasket: () => void;
};

const Ctx = createContext<StoreContext | null>(null);

function api(path: string, init?: RequestInit) {
  return fetch(path, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
}

export function AppStoreProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<StoreState>(initialState);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    let live = true;
    api("/api/bootstrap")
      .then((r) => {
        if (!r.ok) throw new Error(`bootstrap ${r.status}`);
        return r.json() as Promise<BootstrapPayload>;
      })
      .then((payload) => {
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
          basket: payload.basket,
        });
      })
      .catch((error) => console.error("LocalPrices bootstrap failed", error))
      .finally(() => live && setHydrated(true));
    return () => {
      live = false;
    };
  }, []);

  const patch = useCallback(
    (p: Partial<StoreState> | ((s: StoreState) => Partial<StoreState>)) =>
      setState((s) => ({ ...s, ...(typeof p === "function" ? p(s) : p) })),
    [],
  );

  const value = useMemo<StoreContext>(() => {
    const marketsInRadius = MARKETS.map((m) => ({
      ...m,
      distance: distanceKm(state.location, m),
    }))
      .filter((m) => m.distance <= state.radius)
      .sort((a, b) => a.distance - b.distance);

    const basketEntries = Object.entries(state.basket)
      .filter(([, qty]) => qty > 0)
      .map(([productId, qty]) => ({ productId, qty }));

    return {
      ...state,
      hydrated,
      marketsInRadius,
      basketEntries,
      basketCount: basketEntries.reduce((s, e) => s + e.qty, 0),
      setLocation: (location) => {
        patch({ location });
        void api("/api/location", {
          method: "PUT",
          body: JSON.stringify({ ...location, radius: state.radius }),
        });
      },
      setRadius: (radius) => {
        patch({ radius });
        void api("/api/location", {
          method: "PUT",
          body: JSON.stringify({ ...state.location, radius }),
        });
      },
      setMaxStops: (maxStops) => patch({ maxStops }),
      toggleSelected: (id) => {
        patch((s) => ({
          selected: s.selected.includes(id)
            ? s.selected.filter((x) => x !== id)
            : [...s.selected, id],
        }));
        void api(`/api/stores/${id}/toggle`, { method: "POST" });
      },
      toggleFavorite: (id) =>
        patch((s) => ({
          favorites: s.favorites.includes(id)
            ? s.favorites.filter((x) => x !== id)
            : [...s.favorites, id],
        })),
      addToBasket: (productId, qty = 1) => {
        const nextQty = (state.basket[productId] ?? 0) + qty;
        patch((s) => ({ basket: { ...s.basket, [productId]: nextQty } }));
        void api(`/api/basket/${productId}`, { method: "PUT", body: JSON.stringify({ quantity: nextQty }) });
      },
      setQty: (productId, qty) => {
        const safeQty = Math.max(0, qty);
        patch((s) => {
          const next = { ...s.basket };
          if (safeQty <= 0) delete next[productId];
          else next[productId] = safeQty;
          return { basket: next };
        });
        void api(`/api/basket/${productId}`, { method: "PUT", body: JSON.stringify({ quantity: safeQty }) });
      },
      clearBasket: () => {
        patch({ basket: {} });
        void api("/api/basket", { method: "DELETE" });
      },
    };
  }, [state, hydrated, patch]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useStore must be used within AppStoreProvider");
  return ctx;
}

/** Aktive Vergleichsmärkte: gewählte Märkte innerhalb des Radius. */
export function useActiveMarketIds() {
  const { selected, marketsInRadius } = useStore();
  return useMemo(() => {
    const inRadius = marketsInRadius.map((m) => m.id);
    return selected.filter((id) => inRadius.includes(id));
  }, [selected, marketsInRadius]);
}

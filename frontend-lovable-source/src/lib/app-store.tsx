import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { DEFAULT_LOCATION, MARKETS, distanceKm } from "@/data/demo";

type Location = { lat: number; lng: number; label: string };

type StoreState = {
  location: Location;
  radius: number;
  maxStops: number;
  selected: string[];
  favorites: string[];
  basket: Record<string, number>;
};

const STORAGE_KEY = "localprices.state.v1";

const initialState: StoreState = {
  location: DEFAULT_LOCATION,
  radius: 10,
  maxStops: 2,
  selected: ["rewe-hundertmark", "aldi-dierdorf", "lidl-dierdorf"],
  favorites: ["rewe-hundertmark"],
  basket: { p2: 1, p5: 1, p16: 2, p9: 1, p20: 2, p23: 1 },
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

export function AppStoreProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<StoreState>(initialState);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) setState({ ...initialState, ...(JSON.parse(raw) as StoreState) });
    } catch {
      /* ignore */
    }
    setHydrated(true);
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
      setLocation: (location) => patch({ location }),
      setRadius: (radius) => patch({ radius }),
      setMaxStops: (maxStops) => patch({ maxStops }),
      toggleSelected: (id) =>
        patch((s) => ({
          selected: s.selected.includes(id)
            ? s.selected.filter((x) => x !== id)
            : [...s.selected, id],
        })),
      toggleFavorite: (id) =>
        patch((s) => ({
          favorites: s.favorites.includes(id)
            ? s.favorites.filter((x) => x !== id)
            : [...s.favorites, id],
        })),
      addToBasket: (productId, qty = 1) =>
        patch((s) => ({ basket: { ...s.basket, [productId]: (s.basket[productId] ?? 0) + qty } })),
      setQty: (productId, qty) =>
        patch((s) => {
          const next = { ...s.basket };
          if (qty <= 0) delete next[productId];
          else next[productId] = qty;
          return { basket: next };
        }),
      clearBasket: () => patch({ basket: {} }),
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
    const active = selected.filter((id) => inRadius.includes(id));
    return active.length > 0 ? active : inRadius;
  }, [selected, marketsInRadius]);
}

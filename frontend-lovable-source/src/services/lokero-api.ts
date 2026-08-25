/**
 * Zentrale Datenzugriffsschicht des Lokero-Frontends.
 *
 * In Produktion werden die echten FastAPI-Endpunkte unter /api/lokero bzw.
 * /api/bootstrap verwendet. In der Lovable-Preview (oder bei nicht erreichbarem
 * Backend) fallen die Funktionen bewusst auf die vorhandenen Previewdaten zurück.
 * So bleibt das eingefrorene Design unabhängig vom Backend testbar.
 */
import {
  ALTERNATIVES,
  CURRENT_REGION,
  REGIONS,
  CATEGORIES,
  FAVORITE_MARKET_IDS,
  FAVORITE_PRODUCTS,
  MARKETS,
  MARKET_PRICES,
  OFFERS,
  OFFER_WEEK,
  OPTIMIZED_TRIP,
  PRICE_ALERTS,
  PRODUCTS,
  WEEKLY_SAVINGS,
  type Alternative,
  type Category,
  type CategoryId,
  type DietTag,
  type Market,
  type Offer,
  type OptimizedTrip,
  type PriceAlert,
  type Product,
  type Region,
  type RegionStatus,
} from "@/data/lokero";

export type {
  Market,
  Offer,
  Product,
  OptimizedTrip,
  PriceAlert,
  Alternative,
  Category,
  Region,
  RegionStatus,
};

export type FeatureFlags = {
  markets: boolean;
  offers: boolean;
  favorites: boolean;
  shopping_list: boolean;
  region_availability: boolean;
  optimization: boolean;
  savings: boolean;
  normal_price_badges: boolean;
  price_alerts: boolean;
  product_alternatives: boolean;
  reviewer_mode: boolean;
};

export const PREVIEW_FEATURES: FeatureFlags = {
  markets: true,
  offers: true,
  favorites: true,
  shopping_list: true,
  region_availability: true,
  optimization: true,
  savings: true,
  normal_price_badges: true,
  price_alerts: true,
  product_alternatives: true,
  reviewer_mode: false,
};

export type BootstrapPayload = {
  location: { lat: number; lng: number; label: string };
  radius: number;
  selected: string[];
  favorites: string[];
  activeSelected: string[];
  basket: Record<string, number>;
  markets: Array<Record<string, unknown>>;
  products: Array<Record<string, unknown>>;
  prices: Array<Record<string, unknown>>;
};

export type ReviewerStatus = {
  reviewer: boolean;
  expiresAt?: string | null;
  label?: string | null;
};

export type ReviewOffer = {
  productId: string;
  marketId: string;
  offerId: string;
  provenanceId: number | null;
  prospectArchiveId: number | null;
  prospectPage: number | null;
  prospectPages: number[];
  sourceText: string | null;
  reviewStatus: string | null;
  reviewIssueType: string | null;
  reviewNotes: string | null;
  product?: Record<string, unknown>;
  market?: Record<string, unknown>;
  price?: Record<string, unknown>;
  auditUrl?: string;
};

const DEFAULT_CATEGORY: CategoryId = "sonstiges";
const KNOWN_CATEGORY_IDS = new Set(CATEGORIES.map((c) => c.id));
const KNOWN_CHAINS = new Set(["REWE", "Lidl", "ALDI SÜD", "Netto", "EDEKA"]);

let runtimeProducts: Product[] = [...PRODUCTS];
let runtimeMarkets: Market[] = [...MARKETS];
let runtimeOffers: Offer[] = [...OFFERS];
let backendReachable: boolean | null = null;

const productIndex = () => new Map(runtimeProducts.map((p) => [p.id, p]));
const marketIndex = () => new Map(runtimeMarkets.map((m) => [m.id, m]));
const categoryIndex = new Map(CATEGORIES.map((c) => [c.id, c]));

function categoryId(value: unknown): CategoryId {
  const raw = String(value ?? "");
  return KNOWN_CATEGORY_IDS.has(raw as CategoryId) ? (raw as CategoryId) : DEFAULT_CATEGORY;
}

function chain(value: unknown): Market["chain"] {
  const raw = String(value ?? "REWE");
  return (KNOWN_CHAINS.has(raw) ? raw : "REWE") as Market["chain"];
}

function asProduct(row: Record<string, unknown>): Product {
  return {
    id: String(row.id ?? ""),
    name: String(row.name ?? ""),
    brand: String(row.brand ?? ""),
    amount: String(row.amount ?? row.unit ?? ""),
    detail: row.detail ? String(row.detail) : undefined,
    category: categoryId(row.category),
    ean: String(row.ean ?? ""),
    tags: Array.isArray(row.tags) ? (row.tags as DietTag[]) : [],
  };
}

function asMarket(row: Record<string, unknown>): Market {
  return {
    id: String(row.id ?? ""),
    name: String(row.name ?? ""),
    chain: chain(row.chain),
    street: String(row.street ?? ""),
    city: String(row.city ?? ""),
    lat: Number(row.lat ?? 0),
    lng: Number(row.lng ?? 0),
    openUntil: String(row.openUntil ?? ""),
    isOpen: row.isOpen !== false,
    distanceKm: Number(row.distanceKm ?? 0),
    savingPotential: Number(row.savingPotential ?? 0),
    strength: String(row.strength ?? ""),
  };
}

function asOffer(row: Record<string, unknown>): Offer {
  return {
    productId: String(row.productId ?? ""),
    marketId: String(row.marketId ?? ""),
    price: Number(row.price ?? 0),
    oldPrice: row.oldPrice == null ? undefined : Number(row.oldPrice),
    discount: row.discount == null ? undefined : Number(row.discount),
    basePrice: row.basePrice == null ? undefined : String(row.basePrice),
    leafletPage: row.leafletPage == null ? undefined : Number(row.leafletPage),
    validFrom: String(row.validFrom ?? ""),
    validUntil: String(row.validUntil ?? row.validTo ?? ""),
  };
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) throw new Error(`Lokero API ${response.status}: ${path}`);
  backendReachable = true;
  return (await response.json()) as T;
}

async function realOrFallback<T>(real: () => Promise<T>, fallback: () => T | Promise<T>): Promise<T> {
  try {
    return await real();
  } catch {
    backendReachable = false;
    return await fallback();
  }
}

export function isBackendReachable() {
  return backendReachable;
}

/* ---------- Bootstrap / Feature Flags ---------- */

export async function fetchFeatures(): Promise<{ features: FeatureFlags; reviewer: boolean }> {
  return realOrFallback(
    () => api<{ features: FeatureFlags; reviewer: boolean }>("/api/lokero/features"),
    () => ({ features: PREVIEW_FEATURES, reviewer: false }),
  );
}

export async function fetchBootstrap(): Promise<BootstrapPayload | null> {
  try {
    const payload = await api<BootstrapPayload>("/api/bootstrap");
    runtimeProducts = (payload.products ?? []).map((row) => asProduct(row));
    runtimeMarkets = (payload.markets ?? []).map((row) => asMarket(row));
    runtimeOffers = (payload.prices ?? []).map((row) =>
      asOffer({
        ...row,
        validUntil: (row.offer as Record<string, unknown> | undefined)?.until ?? row.validTo,
        oldPrice: row.referencePrice,
        discount: row.discountPercent,
      }),
    );
    return payload;
  } catch {
    backendReachable = false;
    return null;
  }
}

export async function persistLocation(input: { lat: number; lng: number; label: string; radius: number }) {
  try {
    await api("/api/location", { method: "PUT", body: JSON.stringify(input) });
  } catch {
    // Preview/offline: local state remains authoritative until the backend returns.
  }
}

export async function persistBasketQuantity(productId: string, quantity: number) {
  try {
    await api(`/api/basket/${encodeURIComponent(productId)}`, {
      method: "PUT",
      body: JSON.stringify({ quantity }),
    });
  } catch {
    // best-effort sync
  }
}

export async function persistBasketClear() {
  try {
    await api("/api/basket", { method: "DELETE" });
  } catch {
    // best-effort sync
  }
}

export async function persistMarketToggle(marketId: string) {
  try {
    return await api(`/api/stores/${encodeURIComponent(marketId)}/toggle`, { method: "POST" });
  } catch {
    return null;
  }
}

/* ---------- Synchrone Lookups ---------- */

export function getProduct(id: string): Product | undefined {
  return productIndex().get(id);
}
export function getMarket(id: string): Market | undefined {
  return marketIndex().get(id);
}
export function getCategory(id: CategoryId): Category | undefined {
  return categoryIndex.get(id);
}
export function listCategories(): Category[] {
  return CATEGORIES;
}
export function getOfferFor(productId: string): Offer | undefined {
  return runtimeOffers.find((o) => o.productId === productId);
}
export function bestPriceFor(productId: string): { price: number; marketId: string } | undefined {
  const rows = runtimeOffers.filter((o) => o.productId === productId).sort((a, b) => a.price - b.price);
  if (rows[0]) return { price: rows[0].price, marketId: rows[0].marketId };
  const fallback = MARKET_PRICES.filter((p) => p.productId === productId).sort((a, b) => a.price - b.price)[0];
  return fallback ? { price: fallback.price, marketId: fallback.marketId } : undefined;
}
export function marketPricesFor(productId: string) {
  const real = runtimeOffers
    .filter((o) => o.productId === productId)
    .map((o) => ({ productId: o.productId, marketId: o.marketId, price: o.price }))
    .sort((a, b) => a.price - b.price);
  return real.length ? real : MARKET_PRICES.filter((p) => p.productId === productId).sort((a, b) => a.price - b.price);
}
export function alternativesFor(productId: string): Alternative[] {
  return ALTERNATIVES.filter((a) => a.productId === productId);
}
export function priceAlertFor(productId: string): PriceAlert | undefined {
  return PRICE_ALERTS.find((a) => a.productId === productId);
}

/* ---------- Märkte / Angebote ---------- */

export async function fetchMarkets(radiusKm = 15): Promise<Market[]> {
  return realOrFallback(
    async () => {
      const rows = await api<Array<Record<string, unknown>>>("/api/lokero/markets");
      runtimeMarkets = rows.map(asMarket);
      return runtimeMarkets.filter((m) => m.distanceKm <= radiusKm || m.distanceKm === 0);
    },
    () => MARKETS.filter((m) => m.distanceKm <= radiusKm),
  );
}

export type OfferFilter = {
  categoryId?: CategoryId | null;
  tag?: DietTag | null;
  marketIds?: string[];
  query?: string;
};

export type OfferView = Offer & { product: Product; market: Market };

export async function fetchOffers(filter: OfferFilter = {}): Promise<OfferView[]> {
  return realOrFallback(
    async () => {
      const params = new URLSearchParams();
      if (filter.query) params.set("q", filter.query);
      if (filter.categoryId) params.set("category", filter.categoryId);
      if (filter.marketIds?.length) params.set("market_ids", filter.marketIds.join(","));
      const rows = await api<Array<Record<string, unknown>>>(`/api/lokero/offers?${params}`);
      const mapped = rows.map((row) => {
        const product = asProduct((row.product ?? {}) as Record<string, unknown>);
        const market = asMarket((row.market ?? {}) as Record<string, unknown>);
        const offer = asOffer(row);
        return { ...offer, product, market };
      });
      runtimeProducts = Array.from(new Map([...runtimeProducts, ...mapped.map((x) => x.product)].map((p) => [p.id, p])).values());
      runtimeMarkets = Array.from(new Map([...runtimeMarkets, ...mapped.map((x) => x.market)].map((m) => [m.id, m])).values());
      runtimeOffers = mapped.map(({ product: _p, market: _m, ...offer }) => offer);
      return filter.tag ? mapped.filter((o) => o.product.tags.includes(filter.tag!)) : mapped;
    },
    () => {
      const q = filter.query?.trim().toLowerCase() ?? "";
      return OFFERS.map((o) => ({
        ...o,
        product: new Map(PRODUCTS.map((p) => [p.id, p])).get(o.productId)!,
        market: new Map(MARKETS.map((m) => [m.id, m])).get(o.marketId)!,
      }))
        .filter((o) => (filter.categoryId ? o.product.category === filter.categoryId : true))
        .filter((o) => (filter.tag ? o.product.tags.includes(filter.tag) : true))
        .filter((o) => (filter.marketIds?.length ? filter.marketIds.includes(o.marketId) : true))
        .filter((o) => (q ? `${o.product.name} ${o.product.brand}`.toLowerCase().includes(q) : true))
        .sort((a, b) => (b.discount ?? 0) - (a.discount ?? 0));
    },
  );
}

export async function fetchOfferWeek() {
  return realOrFallback(() => api<{ from: string; until: string }>("/api/lokero/offer-week"), () => OFFER_WEEK);
}

export async function fetchTopOffers(limit = 6): Promise<OfferView[]> {
  const all = await fetchOffers();
  return all.slice(0, limit);
}

export async function fetchWeeklySavings() {
  return realOrFallback(
    () => api<typeof WEEKLY_SAVINGS & { enabled?: boolean }>("/api/lokero/weekly-savings"),
    () => ({ ...WEEKLY_SAVINGS, enabled: true }),
  );
}

export async function fetchOptimizedTrip(): Promise<OptimizedTrip & { enabled?: boolean }> {
  return realOrFallback(
    async () => {
      const row = await api<Record<string, unknown>>("/api/lokero/optimized-trip");
      if (row.enabled === false) {
        return { ...OPTIMIZED_TRIP, enabled: false, itemCount: Number(row.itemCount ?? 0), total: 0, savings: 0, travelCost: 0, distanceKm: 0, stops: [], combinationLabel: "" };
      }
      const stops = Array.isArray(row.stops)
        ? row.stops.map((s) => {
            const stop = s as Record<string, unknown>;
            return {
              marketId: String(stop.marketId ?? ""),
              total: Number(stop.subtotal ?? stop.total ?? 0),
              itemCount: Number(stop.itemCount ?? 0),
              productIds: Array.isArray(stop.productIds) ? stop.productIds.map(String) : [],
            };
          })
        : [];
      return {
        enabled: true,
        itemCount: Number(row.itemCount ?? 0),
        total: Number(row.total ?? 0),
        savings: Number(row.savings ?? 0),
        travelCost: Number(row.travelCost ?? 0),
        distanceKm: Number(row.travelKm ?? row.distanceKm ?? 0),
        stops,
        combinationLabel: stops.map((s) => getMarket(s.marketId)?.chain).filter(Boolean).join(" + "),
        savingsExplanation: "Verglichen mit dem günstigsten Einkauf bei nur einem Markt.",
      };
    },
    () => ({ ...OPTIMIZED_TRIP, enabled: true }),
  );
}

/* ---------- Favoriten ---------- */

export async function fetchFavoriteProducts() {
  return realOrFallback(
    async () => {
      const products = await api<Array<Record<string, unknown>>>("/api/lokero/favorites/products");
      const mapped = products.map(asProduct);
      runtimeProducts = Array.from(new Map([...runtimeProducts, ...mapped].map((p) => [p.id, p])).values());
      const offers = await fetchOffers();
      return mapped.map((product) => {
        const best = offers.filter((o) => o.productId === product.id).sort((a, b) => a.price - b.price)[0];
        return { productId: product.id, marketId: best?.marketId ?? "", price: best?.price ?? 0 };
      });
    },
    () => FAVORITE_PRODUCTS,
  );
}

export async function fetchFavoriteMarkets(): Promise<Market[]> {
  return realOrFallback(
    async () => {
      const rows = await api<Array<Record<string, unknown>>>("/api/lokero/favorites/markets");
      const mapped = rows.map(asMarket);
      runtimeMarkets = Array.from(new Map([...runtimeMarkets, ...mapped].map((m) => [m.id, m])).values());
      return mapped;
    },
    () => MARKETS.filter((m) => FAVORITE_MARKET_IDS.includes(m.id)),
  );
}

export async function fetchPriceAlerts(): Promise<PriceAlert[]> {
  return realOrFallback(() => api<PriceAlert[]>("/api/lokero/price-alerts"), () => PRICE_ALERTS);
}

/* ---------- Suche ---------- */

export type SearchResult = { categories: Category[]; products: Product[] };

export async function search(query: string): Promise<SearchResult> {
  const q = query.trim();
  if (!q) return { categories: [], products: [] };
  return realOrFallback(
    async () => {
      const row = await api<{ categories: Array<Record<string, unknown>>; products: Array<Record<string, unknown>> }>(`/api/lokero/search?q=${encodeURIComponent(q)}`);
      const products = row.products.map(asProduct);
      runtimeProducts = Array.from(new Map([...runtimeProducts, ...products].map((p) => [p.id, p])).values());
      const categories = row.categories.map((c) => ({
        id: categoryId(c.id),
        label: String(c.label ?? ""),
        icon: String(c.icon ?? "tag"),
        synonyms: Array.isArray(c.synonyms) ? c.synonyms.map(String) : [],
      }));
      return { categories, products };
    },
    () => {
      const lower = q.toLowerCase();
      const categories = CATEGORIES.filter((c) => c.label.toLowerCase().includes(lower) || c.synonyms.some((s) => s.includes(lower) || lower.includes(s)));
      const ids = new Set(categories.map((c) => c.id));
      const products = PRODUCTS.filter((p) => `${p.name} ${p.brand}`.toLowerCase().includes(lower) || ids.has(p.category)).slice(0, 20);
      return { categories, products };
    },
  );
}

export function suggest(query: string): string[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  return [...CATEGORIES.map((c) => c.label), ...runtimeProducts.map((p) => p.name)]
    .filter((n) => n.toLowerCase().includes(q))
    .slice(0, 6);
}

/* ---------- Regionen ---------- */

export async function fetchRegionStatus(status?: RegionStatus): Promise<Region> {
  if (status) return REGIONS.find((r) => r.status === status) ?? CURRENT_REGION;
  return realOrFallback(() => api<Region>("/api/lokero/regions/status"), () => CURRENT_REGION);
}

export async function fetchRegions(query = ""): Promise<Region[]> {
  return realOrFallback(
    () => api<Region[]>(`/api/lokero/regions?q=${encodeURIComponent(query)}`),
    () => {
      const q = query.trim().toLowerCase();
      return q ? REGIONS.filter((r) => r.regionName.toLowerCase().includes(q) || r.postalCode.startsWith(q)) : REGIONS;
    },
  );
}

export async function notifyRegion(input: { postalCode: string; email?: string }) {
  return realOrFallback(
    () => api("/api/lokero/regions/notify", { method: "POST", body: JSON.stringify(input) }),
    () => ({ ok: true as const, ...input }),
  );
}

/* ---------- Versteckter Prüfmodus ---------- */

export async function fetchReviewerStatus(): Promise<ReviewerStatus> {
  return realOrFallback(() => api<ReviewerStatus>("/api/lokero/review/status"), () => ({ reviewer: false }));
}

export async function unlockReviewer(username: string, password: string, label = "Lokero Prüfgerät") {
  const token = btoa(`${username}:${password}`);
  return api<ReviewerStatus & { ok: boolean }>("/api/lokero/review/unlock", {
    method: "POST",
    headers: { Authorization: `Basic ${token}` },
    body: JSON.stringify({ label, days: 30 }),
  });
}

export async function lockReviewer() {
  return api<{ ok: boolean; removed: boolean }>("/api/lokero/review/lock", { method: "POST" });
}

export async function fetchReviewOffers(marketIds: string[] = []): Promise<ReviewOffer[]> {
  const qs = marketIds.length ? `?market_ids=${encodeURIComponent(marketIds.join(","))}` : "";
  return api<ReviewOffer[]>(`/api/lokero/review/offers${qs}`);
}

export async function reviewOffer(provenanceId: number, status: "correct" | "incorrect") {
  return api<ReviewOffer>(`/api/lokero/review/offers/${provenanceId}`, {
    method: "PUT",
    body: JSON.stringify({ status }),
  });
}

export async function saveReviewerNormalPrice(input: { productId: number; storeId?: number; price: number; notes?: string }) {
  return api("/api/lokero/review/normal-price", { method: "POST", body: JSON.stringify(input) });
}

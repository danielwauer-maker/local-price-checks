import type { CategoryId, Market, Offer, Product } from "@/data/lokero";
import type { OfferView } from "@/services/lokero-api";
import { notifyFavoritesChanged } from "@/services/lokero-state-api";

export type ProductFamily = {
  slug: string;
  label: string;
  category: CategoryId;
  keywords?: string[];
};

export type LastOffer = {
  price: number;
  market: { id: string; name: string; chain: string };
  validFrom: string;
  validUntil: string;
};

async function json<T>(path: string, init?: RequestInit): Promise<T | null> {
  try {
    const response = await fetch(path, {
      credentials: "include",
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...(init?.headers ?? {}),
      },
    });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export async function fetchProductFamilies(): Promise<ProductFamily[]> {
  return (await json<ProductFamily[]>("/api/lokero/product-families")) ?? [];
}

export async function fetchFavoriteFamilies(): Promise<ProductFamily[]> {
  return (await json<ProductFamily[]>("/api/lokero/favorites/families")) ?? [];
}

export async function setFavoriteFamily(slug: string, favorite: boolean): Promise<boolean> {
  try {
    const response = await fetch(`/api/lokero/favorites/families/${encodeURIComponent(slug)}`, {
      credentials: "include",
      method: favorite ? "PUT" : "DELETE",
      headers: { Accept: "application/json" },
    });
    if (response.ok) notifyFavoritesChanged();
    return response.ok;
  } catch {
    return false;
  }
}

function product(row: Record<string, unknown>): Product {
  return {
    id: String(row.id ?? ""),
    name: String(row.name ?? ""),
    brand: String(row.brand ?? ""),
    amount: String(row.amount ?? ""),
    detail: row.detail == null ? undefined : String(row.detail),
    category: String(row.category ?? "sonstiges") as CategoryId,
    ean: String(row.ean ?? ""),
    tags: Array.isArray(row.tags) ? (row.tags as Product["tags"]) : [],
    imageUrl: row.imageUrl == null ? undefined : String(row.imageUrl),
  };
}

function market(row: Record<string, unknown>): Market {
  return {
    id: String(row.id ?? ""),
    name: String(row.name ?? ""),
    chain: String(row.chain ?? "REWE") as Market["chain"],
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

function offer(row: Record<string, unknown>): Offer {
  return {
    productId: String(row.productId ?? ""),
    marketId: String(row.marketId ?? ""),
    price: Number(row.price ?? 0),
    oldPrice: row.oldPrice == null ? undefined : Number(row.oldPrice),
    discount: row.discount == null ? undefined : Number(row.discount),
    basePrice: row.basePrice == null ? undefined : String(row.basePrice),
    leafletPage: row.leafletPage == null ? undefined : Number(row.leafletPage),
    validFrom: String(row.validFrom ?? ""),
    validUntil: String(row.validUntil ?? ""),
  };
}

export async function fetchMatchedFavoriteOffers(): Promise<OfferView[]> {
  const rows = await json<Array<Record<string, unknown>>>("/api/lokero/favorites/matched-offers");
  if (!rows) return [];
  return rows.map((row) => ({
    ...offer(row),
    product: product((row.product ?? {}) as Record<string, unknown>),
    market: market((row.market ?? {}) as Record<string, unknown>),
  }));
}

export async function fetchLastOffer(productId: string): Promise<LastOffer | null> {
  return await json<LastOffer | null>(`/api/lokero/products/${encodeURIComponent(productId)}/last-offer`);
}

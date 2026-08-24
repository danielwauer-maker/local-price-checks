import type { AlternativeKind, Product } from "@/data/lokero";

async function request(path: string, init: RequestInit) {
  try {
    const response = await fetch(path, { credentials: "include", ...init, headers: { Accept: "application/json", ...(init.body ? { "Content-Type": "application/json" } : {}), ...(init.headers ?? {}) } });
    return response.ok;
  } catch {
    return false;
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T | null> {
  try {
    const response = await fetch(path, { credentials: "include", ...init, headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}), ...(init?.headers ?? {}) } });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

/** Best-effort persistence. Local state remains usable in Lovable preview/offline. */
export async function persistProductFavorite(productId: string, favorite: boolean) {
  return request(`/api/lokero/favorites/products/${encodeURIComponent(productId)}`, {
    method: favorite ? "PUT" : "DELETE",
  });
}

export type FavoritePreference = {
  productId: string;
  allowAlternatives: boolean;
};

export type FavoriteAlternative = {
  product: Product;
  price?: number;
  market?: { id: string; name: string; chain: string };
  kind: AlternativeKind;
  reason?: string;
};

export async function fetchFavoritePreferences(): Promise<FavoritePreference[]> {
  return (await requestJson<FavoritePreference[]>("/api/lokero/favorites/preferences")) ?? [];
}

export async function persistFavoriteAlternativePreference(productId: string, allowAlternatives: boolean) {
  return request(`/api/lokero/favorites/products/${encodeURIComponent(productId)}/preferences`, {
    method: "PUT",
    body: JSON.stringify({ allowAlternatives }),
  });
}

export async function fetchFavoriteAlternatives(productId: string): Promise<FavoriteAlternative[]> {
  return (
    (await requestJson<FavoriteAlternative[]>(
      `/api/lokero/favorites/products/${encodeURIComponent(productId)}/alternatives`,
    )) ?? []
  );
}

import type { AlternativeKind, Product } from "@/data/lokero";

export const ACCOUNT_MUTATION_START_EVENT = "spareno:account-mutation-start";
export const ACCOUNT_MUTATION_END_EVENT = "spareno:account-mutation-end";
export const ACCOUNT_SYNC_REQUEST_EVENT = "spareno:account-sync-request";

let suppressFavoritePersistence = 0;

export function runWithoutFavoritePersistence<T>(fn: () => T): T {
  suppressFavoritePersistence += 1;
  try {
    return fn();
  } finally {
    suppressFavoritePersistence = Math.max(0, suppressFavoritePersistence - 1);
  }
}

function dispatchAccountEvent(name: string) {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(name));
}

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
  if (suppressFavoritePersistence > 0) return true;

  dispatchAccountEvent(ACCOUNT_MUTATION_START_EVENT);
  try {
    return await request(`/api/lokero/favorites/products/${encodeURIComponent(productId)}`, {
      method: favorite ? "PUT" : "DELETE",
    });
  } finally {
    dispatchAccountEvent(ACCOUNT_MUTATION_END_EVENT);
    dispatchAccountEvent(ACCOUNT_SYNC_REQUEST_EVENT);
  }
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

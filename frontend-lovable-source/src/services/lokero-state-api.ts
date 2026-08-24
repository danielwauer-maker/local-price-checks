async function request(path: string, init: RequestInit) {
  try {
    const response = await fetch(path, { credentials: "include", ...init, headers: { Accept: "application/json", ...(init.headers ?? {}) } });
    return response.ok;
  } catch {
    return false;
  }
}

/** Best-effort persistence. Local state remains usable in Lovable preview/offline. */
export async function persistProductFavorite(productId: string, favorite: boolean) {
  return request(`/api/lokero/favorites/products/${encodeURIComponent(productId)}`, {
    method: favorite ? "PUT" : "DELETE",
  });
}

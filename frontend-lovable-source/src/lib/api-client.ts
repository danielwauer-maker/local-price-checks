import { withDeviceIdentity } from "./device-identity";

const PATCH_FLAG = "__localPricesApiFetchPatched";

type UsageFeature =
  | "favorite_product_toggle"
  | "favorite_store_toggle"
  | "favorite_alternative_toggle"
  | "shopping_item_quantity"
  | "shopping_item_check"
  | "shopping_clear"
  | "location_update"
  | "profile_update";

function requestUrl(input: RequestInfo | URL): URL | null {
  if (typeof window === "undefined") return null;
  const rawUrl = input instanceof Request ? input.url : String(input);
  return new URL(rawUrl, window.location.href);
}

function isLocalApiRequest(input: RequestInfo | URL): boolean {
  const url = requestUrl(input);
  return Boolean(url && url.origin === window.location.origin && url.pathname.startsWith("/api/"));
}

function usageFeatureFor(input: RequestInfo | URL, init?: RequestInit): UsageFeature | null {
  const url = requestUrl(input);
  if (!url || url.origin !== window.location.origin) return null;
  const method = (init?.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
  const path = url.pathname;

  if (method === "POST" && /^\/api\/stores\/[^/]+\/toggle$/.test(path)) return "favorite_store_toggle";
  if (method === "POST" && /^\/api\/ux\/favorites\/[^/]+\/toggle$/.test(path)) return "favorite_product_toggle";
  if (method === "PUT" && /^\/api\/ux\/favorites\/[^/]+\/alternatives$/.test(path)) return "favorite_alternative_toggle";
  if (method === "PUT" && /^\/api\/basket\/[^/]+$/.test(path)) return "shopping_item_quantity";
  if (method === "PUT" && /^\/api\/ux\/checked\/[^/]+$/.test(path)) return "shopping_item_check";
  if (method === "DELETE" && path === "/api/basket") return "shopping_clear";
  if (method === "PUT" && path === "/api/location") return "location_update";
  if (method === "PUT" && path === "/api/ux/profile") return "profile_update";
  return null;
}

export function installDeviceAwareApiFetch(): void {
  if (typeof window === "undefined") return;
  const target = window as typeof window & { [PATCH_FLAG]?: boolean };
  if (target[PATCH_FLAG]) return;

  const originalFetch = window.fetch.bind(window);
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    if (!isLocalApiRequest(input)) return originalFetch(input, init);

    const baseHeaders = input instanceof Request ? input.headers : undefined;
    const headers = withDeviceIdentity(init?.headers ?? baseHeaders);
    const feature = usageFeatureFor(input, init);

    return originalFetch(input, {
      ...init,
      headers,
      credentials: init?.credentials ?? "include",
    }).then((response) => {
      if (response.ok && feature) {
        void originalFetch("/api/client/activity", {
          method: "POST",
          credentials: "include",
          keepalive: true,
          headers: withDeviceIdentity({ "content-type": "application/json" }),
          body: JSON.stringify({ kind: "feature", feature }),
        }).catch(() => undefined);
      }
      return response;
    });
  };

  target[PATCH_FLAG] = true;
}

export function apiFetch(input: string, init?: RequestInit): Promise<Response> {
  const headers = withDeviceIdentity(init?.headers);
  return window.fetch(input, {
    ...init,
    headers,
    credentials: init?.credentials ?? "include",
  });
}

installDeviceAwareApiFetch();

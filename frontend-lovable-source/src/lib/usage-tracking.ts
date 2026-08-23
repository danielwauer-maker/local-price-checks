import { apiFetch } from "./api-client";

export type UsagePage = "home" | "offers" | "favorites" | "shopping" | "stores" | "settings" | "store_detail" | "other";

export type UsageFeature =
  | "favorite_product_toggle"
  | "favorite_store_toggle"
  | "favorite_alternative_toggle"
  | "shopping_item_add"
  | "shopping_item_remove"
  | "shopping_item_quantity"
  | "shopping_item_check"
  | "shopping_clear"
  | "location_update"
  | "radius_update"
  | "profile_update";

export function usagePageForPath(pathname: string): UsagePage | null {
  if (pathname.startsWith("/auth")) return null;
  if (pathname === "/") return "home";
  if (pathname.startsWith("/angebote")) return "offers";
  if (pathname.startsWith("/favoriten")) return "favorites";
  if (pathname.startsWith("/liste")) return "shopping";
  if (pathname.startsWith("/maerkte")) return "stores";
  if (pathname.startsWith("/markt/")) return "store_detail";
  if (pathname.startsWith("/settings")) return "settings";
  return "other";
}

function send(kind: "page_view" | "pulse" | "feature", page?: UsagePage | null, feature?: UsageFeature) {
  if (typeof window === "undefined") return;
  void apiFetch("/api/client/activity", {
    method: "POST",
    keepalive: true,
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ kind, page: page ?? undefined, feature }),
  }).catch(() => undefined);
}

export function trackPageView(pathname: string): void {
  const page = usagePageForPath(pathname);
  if (page) send("page_view", page);
}

export function trackUsagePulse(pathname: string): void {
  const page = usagePageForPath(pathname);
  if (page) send("pulse", page);
}

export function trackFeature(feature: UsageFeature): void {
  send("feature", undefined, feature);
}

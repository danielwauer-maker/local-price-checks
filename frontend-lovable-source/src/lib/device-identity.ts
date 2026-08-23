const STORAGE_KEY = "lp_device_id";
const PATCH_FLAG = "__localPricesDeviceFetchPatched";

function createDeviceId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `device_${crypto.randomUUID()}`;
  }
  const random = Math.random().toString(36).slice(2);
  return `device_${Date.now().toString(36)}_${random}`;
}

export function getDeviceId(): string {
  if (typeof window === "undefined") return "";
  try {
    const existing = window.localStorage.getItem(STORAGE_KEY);
    if (existing && /^[A-Za-z0-9_-]{16,80}$/.test(existing)) return existing;
    const created = createDeviceId();
    window.localStorage.setItem(STORAGE_KEY, created);
    return created;
  } catch {
    // Safari private mode or disabled storage: the backend cookie still keeps a
    // durable identity, so returning an empty header is safer than rotating IDs.
    return "";
  }
}

export function withDeviceIdentity(headers?: HeadersInit): Headers {
  const result = new Headers(headers ?? {});
  const deviceId = getDeviceId();
  if (deviceId) result.set("x-localprices-client", deviceId);
  return result;
}

export function installDeviceAwareFetch(): void {
  if (typeof window === "undefined") return;
  const target = window as typeof window & { [PATCH_FLAG]?: boolean };
  if (target[PATCH_FLAG]) return;

  const originalFetch = window.fetch.bind(window);
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const rawUrl = input instanceof Request ? input.url : String(input);
    const url = new URL(rawUrl, window.location.href);
    if (url.origin !== window.location.origin || !url.pathname.startsWith("/api/")) {
      return originalFetch(input, init);
    }

    const baseHeaders = input instanceof Request ? input.headers : undefined;
    const headers = withDeviceIdentity(init?.headers ?? baseHeaders);
    return originalFetch(input, { ...init, headers, credentials: init?.credentials ?? "include" });
  };
  target[PATCH_FLAG] = true;
}

installDeviceAwareFetch();

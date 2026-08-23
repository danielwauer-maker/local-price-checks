import { withDeviceIdentity } from "./device-identity";

const PATCH_FLAG = "__localPricesApiFetchPatched";

function isLocalApiRequest(input: RequestInfo | URL): boolean {
  if (typeof window === "undefined") return false;
  const rawUrl = input instanceof Request ? input.url : String(input);
  const url = new URL(rawUrl, window.location.href);
  return url.origin === window.location.origin && url.pathname.startsWith("/api/");
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
    return originalFetch(input, {
      ...init,
      headers,
      credentials: init?.credentials ?? "include",
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

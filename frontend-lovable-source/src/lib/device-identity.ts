const STORAGE_KEY = "lp_device_id";

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

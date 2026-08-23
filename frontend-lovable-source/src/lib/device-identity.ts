const STORAGE_KEY = "lp_device_id";

let memoryDeviceId = "";

function createDeviceId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `device_${crypto.randomUUID()}`;
  }
  const random = Math.random().toString(36).slice(2);
  return `device_${Date.now().toString(36)}_${random}`;
}

export function getDeviceId(): string {
  if (typeof window === "undefined") return "";
  if (memoryDeviceId) return memoryDeviceId;

  try {
    const existing = window.localStorage.getItem(STORAGE_KEY);
    if (existing && /^[A-Za-z0-9_-]{16,80}$/.test(existing)) {
      memoryDeviceId = existing;
      return existing;
    }

    const created = createDeviceId();
    window.localStorage.setItem(STORAGE_KEY, created);
    memoryDeviceId = created;
    return created;
  } catch {
    // Safari can deny localStorage in some privacy contexts. Keep one stable
    // in-memory identity for this page session so parallel bootstrap/heartbeat
    // requests still collapse onto one UserClient. The HttpOnly cookie then
    // preserves the user mapping across later requests/page loads.
    memoryDeviceId = createDeviceId();
    return memoryDeviceId;
  }
}

export function withDeviceIdentity(headers?: HeadersInit): Headers {
  const result = new Headers(headers ?? {});
  const deviceId = getDeviceId();
  if (deviceId) result.set("x-localprices-client", deviceId);
  return result;
}

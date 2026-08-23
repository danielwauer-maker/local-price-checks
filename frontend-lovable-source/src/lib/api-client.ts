import { withDeviceIdentity } from "./device-identity";

export function apiFetch(input: string, init?: RequestInit): Promise<Response> {
  const headers = withDeviceIdentity(init?.headers);
  return fetch(input, {
    ...init,
    headers,
    credentials: init?.credentials ?? "include",
  });
}

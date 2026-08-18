import { registerSW } from "virtual:pwa-register";

function isStandalonePwa(): boolean {
  const nav = navigator as Navigator & { standalone?: boolean };
  return window.matchMedia("(display-mode: standalone)").matches || nav.standalone === true;
}

function sendHeartbeat(forceInstalled = false) {
  const platform = navigator.platform || "";
  fetch("/api/client/heartbeat", {
    method: "POST",
    credentials: "include",
    keepalive: true,
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      pwaInstalled: forceInstalled || isStandalonePwa(),
      platform,
    }),
  }).catch(() => undefined);
}

registerSW({
  immediate: true,

  onRegisteredSW(swUrl, registration) {
    console.log("[PWA] Service Worker registered:", swUrl, registration);
    sendHeartbeat();
  },

  onRegisterError(error) {
    console.error("[PWA] Service Worker registration failed:", error);
    sendHeartbeat();
  },
});

// Chromium/Android reports the install event. iOS does not reliably do so,
// therefore every launch also checks standalone mode above.
window.addEventListener("appinstalled", () => sendHeartbeat(true));
window.addEventListener("pageshow", () => sendHeartbeat());

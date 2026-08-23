import { registerSW } from "virtual:pwa-register";
import { withDeviceIdentity } from "./lib/device-identity";

function isStandalonePwa(): boolean {
  const nav = navigator as Navigator & { standalone?: boolean };
  return window.matchMedia("(display-mode: standalone)").matches || nav.standalone === true;
}

function mobileHint(): boolean {
  const nav = navigator as Navigator & { userAgentData?: { mobile?: boolean } };
  if (typeof nav.userAgentData?.mobile === "boolean") return nav.userAgentData.mobile;
  return /Android|iPhone|iPod|Mobile/i.test(navigator.userAgent || "");
}

function clientPlatform(): string {
  const nav = navigator as Navigator & { userAgentData?: { platform?: string } };
  return nav.userAgentData?.platform || navigator.platform || "";
}

function sendHeartbeat(forceInstalled = false) {
  const standalone = isStandalonePwa();
  fetch("/api/client/heartbeat", {
    method: "POST",
    credentials: "include",
    keepalive: true,
    headers: withDeviceIdentity({ "content-type": "application/json" }),
    body: JSON.stringify({
      pwaInstalled: forceInstalled || standalone,
      standalone,
      platform: clientPlatform(),
      mobile: mobileHint(),
      touchPoints: navigator.maxTouchPoints || 0,
      screenWidth: window.screen?.width || null,
      screenHeight: window.screen?.height || null,
      pixelRatio: window.devicePixelRatio || 1,
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

// Record every launch immediately. Chromium/Android also reports appinstalled;
// iOS is detected through navigator.standalone / display-mode: standalone.
sendHeartbeat();
window.addEventListener("appinstalled", () => sendHeartbeat(true));
window.addEventListener("pageshow", () => sendHeartbeat());

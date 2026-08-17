import { registerSW } from "virtual:pwa-register";

registerSW({
  immediate: true,

  onRegisteredSW(swUrl, registration) {
    console.log("[PWA] Service Worker registered:", swUrl, registration);
  },

  onRegisterError(error) {
    console.error("[PWA] Service Worker registration failed:", error);
  },
});
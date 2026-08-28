import { useEffect } from "react";
import { reconcilePushSubscription } from "@/services/push-api";

export function PushSubscriptionSync() {
  useEffect(() => {
    const reconcile = () => void reconcilePushSubscription();
    reconcile();
    window.addEventListener("focus", reconcile);
    window.addEventListener("online", reconcile);
    const onVisible = () => { if (document.visibilityState === "visible") reconcile(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("focus", reconcile);
      window.removeEventListener("online", reconcile);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);
  return null;
}

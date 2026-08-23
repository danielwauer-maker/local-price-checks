import { useRouterState } from "@tanstack/react-router";
import { useEffect } from "react";

import { trackPageView, trackUsagePulse } from "@/lib/usage-tracking";

const PULSE_MS = 5 * 60 * 1000;

export function UsageTracker() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });

  useEffect(() => {
    trackPageView(pathname);
  }, [pathname]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") trackUsagePulse(pathname);
    }, PULSE_MS);
    return () => window.clearInterval(timer);
  }, [pathname]);

  return null;
}

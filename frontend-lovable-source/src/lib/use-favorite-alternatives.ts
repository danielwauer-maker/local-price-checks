import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api-client";

export function useFavoriteAlternatives() {
  const [preferences, setPreferences] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let live = true;
    apiFetch("/api/ux/favorite-alternatives")
      .then((response) => response.ok ? response.json() : {})
      .then((payload) => live && setPreferences(payload as Record<string, boolean>))
      .catch(() => live && setPreferences({}));
    return () => { live = false; };
  }, []);

  const setEnabled = useCallback((productId: string, enabled: boolean) => {
    setPreferences((current) => ({ ...current, [productId]: enabled }));
    void apiFetch(`/api/ux/favorites/${productId}/alternatives`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ enabled }),
    }).then((response) => {
      if (!response.ok) throw new Error(`favorite alternatives ${response.status}`);
    }).catch(() => {
      setPreferences((current) => ({ ...current, [productId]: !enabled }));
    });
  }, []);

  const removePreference = useCallback((productId: string) => {
    setPreferences((current) => {
      const next = { ...current };
      delete next[productId];
      return next;
    });
  }, []);

  return { preferences, setEnabled, removePreference };
}

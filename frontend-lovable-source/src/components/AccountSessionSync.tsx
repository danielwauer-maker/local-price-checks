import { useEffect, useRef } from "react";
import type { Session } from "@supabase/supabase-js";

import { supabase } from "@/integrations/supabase/client";
import {
  ACCOUNT_PROFILE_STORAGE_KEY,
  linkLokeroAccount,
  rememberLinkedProfile,
} from "@/services/lokero-account-api";

function authOwnsHandoff() {
  if (typeof window === "undefined") return false;
  return window.location.pathname === "/auth"
    && new URLSearchParams(window.location.search).has("returnTo");
}

export function AccountSessionSync() {
  const lastLinkedUserId = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function applySession(session: Session | null) {
      if (cancelled || !session?.user?.id) return;
      if (authOwnsHandoff()) return;
      if (lastLinkedUserId.current === session.user.id) return;

      try {
        const result = await linkLokeroAccount(session);
        if (cancelled) return;
        lastLinkedUserId.current = session.user.id;

        const profileId = result.profileId == null ? "" : String(result.profileId);
        const previousProfileId = window.localStorage.getItem(ACCOUNT_PROFILE_STORAGE_KEY) ?? "";
        if (profileId && profileId !== previousProfileId) {
          rememberLinkedProfile(result);
          window.location.reload();
        }
      } catch (error) {
        console.error("[Spareno] Account-Link fehlgeschlagen", error);
      }
    }

    void supabase.auth.getSession().then(({ data: { session } }) => applySession(session));

    const { data } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!session?.user?.id) {
        lastLinkedUserId.current = null;
        window.localStorage.removeItem(ACCOUNT_PROFILE_STORAGE_KEY);
        return;
      }
      void applySession(session);
    });

    return () => {
      cancelled = true;
      data.subscription.unsubscribe();
    };
  }, []);

  return null;
}

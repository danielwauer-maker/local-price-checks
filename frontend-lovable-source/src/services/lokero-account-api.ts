import type { Session } from "@supabase/supabase-js";

export type AccountLinkResult = {
  linked: boolean;
  profileId?: number;
  email?: string | null;
};

export async function linkLokeroAccount(session: Session): Promise<AccountLinkResult> {
  const response = await fetch("/api/account/link", {
    method: "POST",
    credentials: "include",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${session.access_token}`,
    },
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail || `Account-Link fehlgeschlagen (${response.status})`);
  }
  return (await response.json()) as AccountLinkResult;
}

import type { Session } from "@supabase/supabase-js";

export const ACCOUNT_PROFILE_STORAGE_KEY = "lokero.account.profile-id";

export type AccountLinkResult = {
  linked: boolean;
  profileId?: number;
  email?: string | null;
};

export type AccountNotificationSettings = {
  priceAlerts: boolean;
  newOffers: boolean;
  regionAvailable: boolean;
  favoriteOffers: boolean;
};

export type AccountState = {
  linked: boolean;
  profileId?: number;
  profile?: {
    displayName: string;
    postalCode: string | null;
    city: string | null;
    latitude: number | null;
    longitude: number | null;
    radiusKm: number;
  };
  favoriteProductIds?: string[];
  favoriteMarketIds?: string[];
  favoriteFamilies?: string[];
  favoritePreferences?: Array<{ productId: string; allowAlternatives: boolean }>;
  preferencesInitialized?: boolean;
  preferences?: {
    travelCostPerKm: number;
    notifications: AccountNotificationSettings;
    preferredChains: string[];
    diet: string[];
  };
};

export type AccountPreferencesPatch = {
  travelCostPerKm?: number;
  notifications?: Partial<AccountNotificationSettings>;
  preferredChains?: string[];
  diet?: string[];
  initializeOnly?: boolean;
};

export type AccountProfilePatch = {
  displayName?: string;
  postalCode: string;
  city: string;
  radiusKm?: number;
};

async function parseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail || `Spareno API ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function linkLokeroAccount(session: Session): Promise<AccountLinkResult> {
  const response = await fetch("/api/account/link", {
    method: "POST",
    credentials: "include",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${session.access_token}`,
    },
  });

  return parseJson<AccountLinkResult>(response);
}

export async function fetchAccountState(): Promise<AccountState> {
  const response = await fetch("/api/account/state", {
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  return parseJson<AccountState>(response);
}

export async function persistAccountPreferences(patch: AccountPreferencesPatch): Promise<AccountState> {
  const response = await fetch("/api/account/preferences", {
    method: "PUT",
    credentials: "include",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return parseJson<AccountState>(response);
}

export async function persistAccountProfile(patch: AccountProfilePatch): Promise<AccountState> {
  const response = await fetch("/api/account/profile", {
    method: "PUT",
    credentials: "include",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return parseJson<AccountState>(response);
}

export function rememberLinkedProfile(result: AccountLinkResult) {
  if (typeof window === "undefined" || result.profileId == null) return;
  window.localStorage.setItem(ACCOUNT_PROFILE_STORAGE_KEY, String(result.profileId));
}

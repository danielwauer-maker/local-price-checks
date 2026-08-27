export type SharedListMember = {
  userId: string;
  displayName: string;
  email?: string | null;
  role: "owner" | "editor" | string;
};

export type SharedListSummary = {
  id: string;
  name: string;
  isPersonal: boolean;
  role: string;
  revision: number;
  memberCount: number;
  members: SharedListMember[];
};

export type SharedListItem = {
  id: string;
  productId?: string | null;
  manualText?: string | null;
  quantity: number;
  checked: boolean;
  addedBy?: string | null;
  checkedBy?: string | null;
  product?: {
    id: string;
    name: string;
    brand?: string;
    amount?: string;
    category?: string;
    imageUrl?: string | null;
  } | null;
};

export type SharedListSnapshot = {
  list: SharedListSummary;
  items: SharedListItem[];
};

export type ShoppingListsOverview = {
  enabled: boolean;
  reason?: string;
  activeListId?: string | null;
  lists: SharedListSummary[];
};

export type ListInvite = {
  token: string;
  listId: string;
  listName: string;
  invitedEmail?: string | null;
  expiresAt: string;
};

export type InvitePreview = {
  valid: boolean;
  listName: string;
  inviter: string;
  invitedEmail?: string | null;
  expiresAt: string;
};

export type SharedFavoriteProduct = {
  id: string;
  name: string;
  brand?: string;
  amount?: string;
  category?: string;
  imageUrl?: string | null;
};

export type FavoriteShare = {
  enabled: boolean;
  ownerName: string;
  visibleCount: number;
  token: string;
  items: Array<{ productId: string; visible: boolean; product?: SharedFavoriteProduct | null }>;
};

export type FavoriteShareSettings = {
  enabledForAccount: boolean;
  share: FavoriteShare | null;
};

export type FriendFavorite = {
  shareId: string;
  ownerName: string;
  available: boolean;
  visibleCount: number;
  items: Array<SharedFavoriteProduct | null>;
  inAppEnabled: boolean;
  pushEnabled: boolean;
};

export type FriendFavoriteAlert = {
  shareId: string;
  friendName: string;
  product?: SharedFavoriteProduct | null;
  market?: { id: string; name: string; chain: string } | null;
  price: number;
  validUntil: string;
};

export type FriendFavoritesOverview = {
  enabled: boolean;
  friends: FriendFavorite[];
  alerts: FriendFavoriteAlert[];
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail || `Spareno Sharing API ${response.status}`);
  }
  return (await response.json()) as T;
}

export const fetchShoppingLists = () => request<ShoppingListsOverview>("/api/sharing/lists");
export const fetchActiveShoppingList = () => request<SharedListSnapshot>("/api/sharing/lists/active");
export const createShoppingList = (name: string) => request<SharedListSummary>("/api/sharing/lists", { method: "POST", body: JSON.stringify({ name }) });
export const setActiveShoppingList = (listId: string) => request<SharedListSnapshot>(`/api/sharing/lists/${encodeURIComponent(listId)}/active`, { method: "PUT" });
export const createShoppingListInvite = (listId: string, email?: string) => request<ListInvite>(`/api/sharing/lists/${encodeURIComponent(listId)}/invite`, { method: "POST", body: JSON.stringify({ email: email?.trim() || null }) });
export const inspectShoppingListInvite = (token: string) => request<InvitePreview>(`/api/sharing/lists/invites/${encodeURIComponent(token)}`);
export const acceptShoppingListInvite = (token: string) => request<SharedListSnapshot>(`/api/sharing/lists/invites/${encodeURIComponent(token)}/accept`, { method: "POST" });
export const removeShoppingListMember = (listId: string, userId: string) => request<{ removed: boolean }>(`/api/sharing/lists/${encodeURIComponent(listId)}/members/${encodeURIComponent(userId)}`, { method: "DELETE" });
export const putSharedProduct = (listId: string, productId: string, quantity: number) => request<SharedListSnapshot>(`/api/sharing/lists/${encodeURIComponent(listId)}/items/product/${encodeURIComponent(productId)}`, { method: "PUT", body: JSON.stringify({ quantity }) });
export const addSharedManualItem = (listId: string, text: string, quantity = 1) => request<SharedListSnapshot>(`/api/sharing/lists/${encodeURIComponent(listId)}/items/manual`, { method: "POST", body: JSON.stringify({ text, quantity }) });
export const patchSharedListItem = (listId: string, itemId: string, patch: { quantity?: number; checked?: boolean }) => request<SharedListSnapshot>(`/api/sharing/lists/${encodeURIComponent(listId)}/items/${encodeURIComponent(itemId)}`, { method: "PATCH", body: JSON.stringify(patch) });
export const deleteSharedListItem = (listId: string, itemId: string) => request<SharedListSnapshot>(`/api/sharing/lists/${encodeURIComponent(listId)}/items/${encodeURIComponent(itemId)}`, { method: "DELETE" });
export const clearSharedList = (listId: string) => request<SharedListSnapshot>(`/api/sharing/lists/${encodeURIComponent(listId)}/items`, { method: "DELETE" });

export const fetchFavoriteShareSettings = () => request<FavoriteShareSettings>("/api/sharing/favorites/settings");
export const setFavoriteShareEnabled = (enabled: boolean) => request<FavoriteShare>("/api/sharing/favorites/share", { method: "POST", body: JSON.stringify({ enabled }) });
export const rotateFavoriteShare = () => request<FavoriteShare>("/api/sharing/favorites/share/rotate", { method: "POST" });
export const setSharedFavoriteVisibility = (productId: string, visible: boolean) => request<{ visible: boolean; share?: FavoriteShare | null }>(`/api/sharing/favorites/items/${encodeURIComponent(productId)}/visibility`, { method: "PUT", body: JSON.stringify({ visible }) });
export const fetchPublicFavoriteShare = (token: string) => request<{ available: boolean; ownerName: string; items: SharedFavoriteProduct[] }>(`/api/sharing/favorites/public/${encodeURIComponent(token)}`);
export const subscribeToFavoriteShare = (token: string) => request<{ subscribed: boolean }>(`/api/sharing/favorites/subscriptions/${encodeURIComponent(token)}`, { method: "POST" });
export const unsubscribeFromFavoriteShare = (shareId: string) => request<{ subscribed: boolean }>(`/api/sharing/favorites/subscriptions/${encodeURIComponent(shareId)}`, { method: "DELETE" });
export const updateFriendFavoriteSettings = (shareId: string, patch: { inAppEnabled?: boolean; pushEnabled?: boolean }) => request<{ inAppEnabled: boolean; pushEnabled: boolean }>(`/api/sharing/favorites/subscriptions/${encodeURIComponent(shareId)}`, { method: "PATCH", body: JSON.stringify(patch) });
export const fetchFriendFavorites = () => request<FriendFavoritesOverview>("/api/sharing/favorites/subscriptions");

export function favoriteShareUrl(token: string) {
  if (typeof window === "undefined") return `/favoriten/geteilt/${token}`;
  return `${window.location.origin}/favoriten/geteilt/${token}`;
}

export function favoriteShareQrUrl(token: string) {
  return `/api/sharing/favorites/public/${encodeURIComponent(token)}/qr.svg`;
}

export function shoppingInviteUrl(token: string) {
  if (typeof window === "undefined") return `/liste/einladung/${token}`;
  return `${window.location.origin}/liste/einladung/${token}`;
}

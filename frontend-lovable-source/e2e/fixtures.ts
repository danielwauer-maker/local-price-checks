import { expect, test as base, type Page, type Route } from "@playwright/test";

type QualityState = {
  consoleErrors: string[];
  pageErrors: string[];
  serverErrors: string[];
  expectedServerErrors: RegExp[];
  expectedConsoleErrors: RegExp[];
};

type ApiState = {
  favoriteProducts: Set<string>;
  favoriteFamilies: Set<string>;
  preferences: Map<string, boolean>;
  accountLinked: boolean;
  accountFavoriteProducts: Set<string>;
  sharedRevision: number;
  sharedButterQuantity: number;
  sharedButterChecked: boolean;
  favoriteShareCreated: boolean;
  sharedFavoriteVisible: boolean;
  friendSubscribed: boolean;
  friendInAppEnabled: boolean;
};

const products = {
  "gouda-milbona": {
    id: "gouda-milbona",
    name: "Milbona Gouda jung",
    brand: "Milbona",
    amount: "250 g",
    category: "kaese",
    ean: "20123451",
    tags: ["vegetarisch", "glutenfrei"],
  },
  butter: {
    id: "butter",
    name: "Butter mildgesäuert",
    brand: "Kerrygold",
    amount: "250 g",
    category: "molkerei",
    ean: "20123464",
    tags: ["vegetarisch", "glutenfrei"],
  },
  "coca-cola-15": {
    id: "coca-cola-15",
    name: "Coca-Cola Original",
    brand: "Coca-Cola",
    amount: "1,5 l",
    category: "getraenke",
    ean: "20123456",
    tags: ["vegan", "glutenfrei"],
  },
} as const;

const families = [
  { slug: "butter", label: "Butter", category: "molkerei", keywords: ["butter"] },
  { slug: "cola", label: "Cola", category: "getraenke", keywords: ["cola"] },
  { slug: "kaese", label: "Käse", category: "kaese", keywords: ["käse"] },
];

const initialStore = {
  location: { lat: 50.6011, lng: 7.5719, label: "Steimel / Puderbach" },
  radius: 15,
  list: { butter: 1 },
  favoriteProducts: ["gouda-milbona"],
  favoriteMarkets: ["lidl-puderbach", "rewe-puderbach"],
  alerts: {},
  preferredChains: ["REWE", "Lidl", "ALDI SÜD", "Netto", "EDEKA"],
  travelCostPerKm: 0.3,
  notifications: {
    priceAlerts: true,
    newOffers: true,
    regionAvailable: true,
    favoriteOffers: false,
  },
  diet: [],
  regionStatusOverride: "auto",
};

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json; charset=utf-8",
    body: JSON.stringify(body),
  });
}

async function installApiFixture(page: Page, state: ApiState) {
  await page.route("**/__e2e/supabase/**", (route) => json(route, {}, 404));
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    if (path === "/api/bootstrap") return route.fulfill({ status: 204 });
    if (path === "/api/account/status") return json(route, { linked: state.accountLinked });
    if (path === "/api/account/state") {
      return json(route, {
        linked: state.accountLinked,
        profileId: state.accountLinked ? 17 : undefined,
        favoriteProductIds: [...state.accountFavoriteProducts],
        preferencesInitialized: true,
        preferences: {
          travelCostPerKm: 0.3,
          notifications: initialStore.notifications,
          preferredChains: initialStore.preferredChains,
          diet: [],
        },
      });
    }
    if (path === "/api/account/preferences" && method === "PUT") {
      return json(route, {
        linked: state.accountLinked,
        profileId: 17,
        favoriteProductIds: [...state.accountFavoriteProducts],
        preferencesInitialized: true,
        preferences: {
          travelCostPerKm: 0.3,
          notifications: initialStore.notifications,
          preferredChains: initialStore.preferredChains,
          diet: [],
        },
      });
    }

    const sharedList = {
      id: "family-list",
      name: "Familie Müller",
      isPersonal: false,
      role: "owner",
      revision: state.sharedRevision,
      memberCount: 2,
      members: [
        { userId: "owner-1", displayName: "Daniel", email: "daniel@example.test", role: "owner" },
        { userId: "friend-1", displayName: "Anna", email: "anna@example.test", role: "editor" },
      ],
    };
    const sharedSnapshot = () => ({
      list: { ...sharedList, revision: state.sharedRevision },
      items: state.sharedButterQuantity > 0
        ? [{ id: "shared-butter", productId: "butter", quantity: state.sharedButterQuantity, checked: state.sharedButterChecked, addedBy: "Daniel", product: products.butter }]
        : [],
    });
    if (path === "/api/sharing/lists" && method === "GET") {
      return json(route, state.accountLinked
        ? { enabled: true, activeListId: sharedList.id, lists: [sharedList] }
        : { enabled: false, reason: "account_required", activeListId: null, lists: [] });
    }
    if (path === "/api/sharing/lists/active" && method === "GET") return json(route, sharedSnapshot());
    if (path === `/api/sharing/lists/${sharedList.id}/invite` && method === "POST") {
      return json(route, { token: "invite-token", listId: sharedList.id, listName: sharedList.name, invitedEmail: "anna@example.test", expiresAt: "2099-01-01T00:00:00Z" });
    }
    if (path === "/api/sharing/lists/invites/invite-token" && method === "GET") {
      return json(route, { valid: true, listName: sharedList.name, inviter: "Daniel", invitedEmail: "anna@example.test", expiresAt: "2099-01-01T00:00:00Z" });
    }
    if (path === "/api/sharing/lists/invites/invite-token/accept" && method === "POST") return json(route, sharedSnapshot());
    if (path === `/api/sharing/lists/${sharedList.id}/items/product/butter` && method === "PUT") {
      const body = request.postDataJSON() as { quantity?: number };
      state.sharedButterQuantity = Math.max(0, Number(body.quantity ?? 0));
      state.sharedRevision += 1;
      return json(route, sharedSnapshot());
    }
    if (path === `/api/sharing/lists/${sharedList.id}/items/shared-butter` && method === "PATCH") {
      const body = request.postDataJSON() as { quantity?: number; checked?: boolean };
      if (body.quantity !== undefined) state.sharedButterQuantity = Math.max(0, Number(body.quantity));
      if (body.checked !== undefined) state.sharedButterChecked = body.checked;
      state.sharedRevision += 1;
      return json(route, sharedSnapshot());
    }

    const favoriteShare = () => ({
      enabled: true,
      ownerName: "Daniel",
      visibleCount: state.sharedFavoriteVisible ? 1 : 0,
      token: "favorite-token",
      items: [{ productId: "gouda-milbona", visible: state.sharedFavoriteVisible, product: products["gouda-milbona"] }],
    });
    const friendOverview = () => ({
      enabled: state.accountLinked,
      friends: state.friendSubscribed ? [{ shareId: "friend-share", ownerName: "Anna", available: true, visibleCount: 1, items: [products.butter], inAppEnabled: state.friendInAppEnabled, pushEnabled: false }] : [],
      alerts: [],
    });
    if (path === "/api/sharing/favorites/settings" && method === "GET") {
      return json(route, { enabledForAccount: state.accountLinked, share: state.favoriteShareCreated ? favoriteShare() : null });
    }
    if (path === "/api/sharing/favorites/share" && method === "POST") {
      state.favoriteShareCreated = true;
      return json(route, favoriteShare());
    }
    if (path === "/api/sharing/favorites/items/gouda-milbona/visibility" && method === "PUT") {
      const body = request.postDataJSON() as { visible?: boolean };
      state.sharedFavoriteVisible = body.visible === true;
      return json(route, { visible: state.sharedFavoriteVisible, share: favoriteShare() });
    }
    if (path === "/api/sharing/favorites/public/favorite-token" && method === "GET") {
      return json(route, { available: true, ownerName: "Daniel", items: state.sharedFavoriteVisible ? [products["gouda-milbona"]] : [] });
    }
    if (path === "/api/sharing/favorites/subscriptions" && method === "GET") return json(route, friendOverview());
    if (path === "/api/sharing/favorites/subscriptions/friend-share" && method === "PATCH") {
      const body = request.postDataJSON() as { inAppEnabled?: boolean };
      if (body.inAppEnabled !== undefined) state.friendInAppEnabled = body.inAppEnabled;
      return json(route, { inAppEnabled: state.friendInAppEnabled, pushEnabled: false });
    }
    if (path === "/api/lokero/product-families") return json(route, families);
    if (path === "/api/lokero/favorites/families" && method === "GET") {
      return json(
        route,
        families.filter((family) => state.favoriteFamilies.has(family.slug)),
      );
    }
    if (path.startsWith("/api/lokero/favorites/families/") && ["PUT", "DELETE"].includes(method)) {
      const slug = decodeURIComponent(path.split("/").at(-1) ?? "");
      if (method === "PUT") state.favoriteFamilies.add(slug);
      else state.favoriteFamilies.delete(slug);
      return json(route, { ok: true });
    }
    if (path === "/api/lokero/favorites/preferences") {
      return json(
        route,
        [...state.preferences].map(([productId, allowAlternatives]) => ({
          productId,
          allowAlternatives,
        })),
      );
    }
    if (path.endsWith("/preferences") && method === "PUT") {
      const productId = decodeURIComponent(path.split("/").at(-2) ?? "");
      const body = request.postDataJSON() as { allowAlternatives?: boolean };
      state.preferences.set(productId, body.allowAlternatives === true);
      return json(route, { ok: true });
    }
    if (path.endsWith("/alternatives")) {
      return json(route, [
        {
          product: products["coca-cola-15"],
          price: 0.99,
          kind: "aehnlich",
          reason: "Günstigste passende Alternative",
        },
      ]);
    }
    if (path === "/api/lokero/favorites/products" && method === "GET") {
      return json(
        route,
        [...state.favoriteProducts]
          .map((id) => products[id as keyof typeof products])
          .filter(Boolean),
      );
    }
    if (path.startsWith("/api/lokero/favorites/products/") && ["PUT", "DELETE"].includes(method)) {
      const productId = decodeURIComponent(path.split("/").at(-1) ?? "");
      if (method === "PUT") state.favoriteProducts.add(productId);
      else state.favoriteProducts.delete(productId);
      if (state.accountLinked) {
        if (method === "PUT") state.accountFavoriteProducts.add(productId);
        else state.accountFavoriteProducts.delete(productId);
      }
      return json(route, { ok: true });
    }
    if (["PUT", "POST", "DELETE", "PATCH"].includes(method)) return json(route, { ok: true });
    return route.fulfill({ status: 204 });
  });
}

export const test = base.extend<{
  quality: QualityState;
  apiState: ApiState;
  expectServerError: (pattern: RegExp) => void;
  expectConsoleError: (pattern: RegExp) => void;
}>({
  apiState: async ({}, use) => {
    await use({
      favoriteProducts: new Set(["gouda-milbona"]),
      favoriteFamilies: new Set(),
      preferences: new Map(),
      accountLinked: false,
      accountFavoriteProducts: new Set(["gouda-milbona"]),
      sharedRevision: 1,
      sharedButterQuantity: 1,
      sharedButterChecked: false,
      favoriteShareCreated: false,
      sharedFavoriteVisible: true,
      friendSubscribed: false,
      friendInAppEnabled: true,
    });
  },
  quality: async ({}, use) => {
    const state: QualityState = {
      consoleErrors: [],
      pageErrors: [],
      serverErrors: [],
      expectedServerErrors: [],
      expectedConsoleErrors: [],
    };
    await use(state);
    const unexpected5xx = state.serverErrors.filter(
      (entry) => !state.expectedServerErrors.some((pattern) => pattern.test(entry)),
    );
    // WebKit reports a same-origin fetch cancelled by a full page navigation as
    // this synthetic CORS pageerror. Keep the exception narrow to the local
    // intercepted account endpoint; every other pageerror still fails the gate.
    const unexpectedPageErrors = state.pageErrors.filter((entry) =>
      !/^\/127\.0\.0\.1:4174\/api\/account\/state due to access control checks\.$/.test(entry),
    );
    expect(unexpectedPageErrors, "uncaught browser exceptions").toEqual([]);
    const unexpectedConsoleErrors = state.consoleErrors.filter(
      (entry) => !state.expectedConsoleErrors.some((pattern) => pattern.test(entry)),
    );
    expect(unexpectedConsoleErrors, "unexpected browser console errors").toEqual([]);
    expect(unexpected5xx, "unexpected HTTP 5xx responses").toEqual([]);
  },
  expectServerError: async ({ quality }, use) => {
    await use((pattern: RegExp) => quality.expectedServerErrors.push(pattern));
  },
  expectConsoleError: async ({ quality }, use) => {
    await use((pattern: RegExp) => quality.expectedConsoleErrors.push(pattern));
  },
  page: async ({ page, apiState, quality }, use) => {
    page.on("console", (message) => {
      if (message.type() === "error") {
        const location = message.location();
        quality.consoleErrors.push(
          `${message.text()}${location.url ? ` @ ${location.url}` : ""}`,
        );
      }
    });
    page.on("pageerror", (error) => quality.pageErrors.push(error.message));
    page.on("response", (response) => {
      if (response.status() >= 500) {
        quality.serverErrors.push(`${response.status()} ${response.url()}`);
      }
    });
    await page.addInitScript((state) => {
      if (!window.localStorage.getItem("lokero.state.v1")) {
        window.localStorage.setItem("lokero.state.v1", JSON.stringify(state));
      }
      window.localStorage.setItem("spareno_onboarding_v1_completed", "1");
    }, initialStore);
    await page.addInitScript(() => {
      const sources: Array<EventTarget & { url: string; close: () => void; onopen?: (event: Event) => void }> = [];
      class E2EEventSource extends EventTarget {
        url: string;
        withCredentials = true;
        readyState = 1;
        onopen?: (event: Event) => void;
        onerror?: (event: Event) => void;
        onmessage?: (event: MessageEvent) => void;
        constructor(url: string | URL) {
          super();
          this.url = String(url);
          sources.push(this);
          queueMicrotask(() => this.onopen?.(new Event("open")));
        }
        close() { this.readyState = 2; }
      }
      Object.defineProperty(window, "EventSource", { configurable: true, value: E2EEventSource });
      Object.defineProperty(window, "__e2eEmitServerEvent", {
        configurable: true,
        value: (urlPart: string, eventName: string, data = "{}") => {
          for (const source of sources) {
            if (source.url.includes(urlPart)) source.dispatchEvent(new MessageEvent(eventName, { data }));
          }
        },
      });
    });
    await page.route("https://fonts.googleapis.com/**", (route) =>
      route.fulfill({ status: 200, contentType: "text/css", body: "" }),
    );
    await page.route("https://*.basemaps.cartocdn.com/**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "image/png",
        body: Buffer.from(
          "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
          "base64",
        ),
      }),
    );
    await installApiFixture(page, apiState);
    await use(page);
  },
});

export async function openApp(page: Page, path: string) {
  await page.goto(path);
  await expect(page.locator("html")).toHaveAttribute("data-app-ready", "true");
  await expect(page.locator(".spareno-splash")).toBeHidden();
}

export async function emitServerEvent(page: Page, urlPart: string, eventName: string, data = "{}") {
  await page.evaluate(({ urlPart, eventName, data }) => {
    (window as typeof window & { __e2eEmitServerEvent: (url: string, event: string, payload: string) => void })
      .__e2eEmitServerEvent(urlPart, eventName, data);
  }, { urlPart, eventName, data });
}

export { expect } from "@playwright/test";

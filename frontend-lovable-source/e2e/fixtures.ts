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
    if (path === "/api/account/status") return json(route, { linked: false });
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
    expect(state.pageErrors, "uncaught browser exceptions").toEqual([]);
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
    }, initialStore);
    await page.route("https://fonts.googleapis.com/**", (route) =>
      route.fulfill({ status: 200, contentType: "text/css", body: "" }),
    );
    await page.route("https://*.basemaps.cartocdn.com/**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "image/png",
        body: Buffer.from(
          "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAF/gL+3MxZ5wAAAABJRU5ErkJggg==",
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

export { expect } from "@playwright/test";

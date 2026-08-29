import { expect, test, type BrowserContext, type Page } from "@playwright/test";

test.skip(process.env.PLAYWRIGHT_REAL_BACKEND !== "1", "Requires the isolated real FastAPI backend.");

const clientKeys = {
  accountADevice1: "spareno-e2e-device-a1-001",
  accountADevice2: "spareno-e2e-device-a2-002",
  accountBDevice1: "spareno-e2e-device-b1-003",
};

async function openLinkedDevice(context: BrowserContext, clientKey: string, path = "/"): Promise<Page> {
  await context.addCookies([
    { name: "lp_client_id", value: clientKey, domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" },
  ]);
  await context.addInitScript(() => {
    window.localStorage.setItem("spareno_onboarding_v1_completed", "1");
    window.localStorage.setItem("lokero.account.profile-id", "integration-linked");
  });
  const page = await context.newPage();
  await page.goto(path, { waitUntil: "domcontentloaded" });
  await page.locator("html[data-app-ready='true']").waitFor();
  return page;
}

async function api<T>(page: Page, path: string, init?: RequestInit): Promise<T> {
  return page.evaluate(async ({ path, init }) => {
    const response = await fetch(path, init);
    if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
    return response.json();
  }, { path, init }) as Promise<T>;
}

async function waitForJsonResponse<T>(
  page: Page,
  path: string,
  predicate: (payload: T) => boolean,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timeout = setTimeout(() => {
      page.off("response", inspect);
      reject(new Error(`Timed out waiting for ${path}`));
    }, 10_000);
    const inspect = async (response: import("@playwright/test").Response) => {
      if (new URL(response.url()).pathname !== path || !response.ok()) return;
      try {
        const payload = await response.json() as T;
        if (!predicate(payload)) return;
        clearTimeout(timeout);
        page.off("response", inspect);
        resolve(payload);
      } catch {
        // A matching URL with a non-JSON response is not the state transition we need.
      }
    };
    page.on("response", inspect);
  });
}

const delay = (milliseconds: number) => new Promise((resolve) => setTimeout(resolve, milliseconds));

type StartupSample = {
  shellMs: number;
  mainDataReadyMs: number;
  bootstrapDurationMs: number;
  bootstrapPayloadBytes: number;
  startupRequestCount: number;
  duplicateRequests: string[];
  apiWaterfallSpanMs: number;
};

async function measureStartup(page: Page, navigate: () => Promise<unknown>): Promise<StartupSample> {
  const startedAt = Date.now();
  const requestStarted = new Map<string, number>();
  const apiRequests: Array<{ key: string; started: number; ended?: number }> = [];
  const onRequest = (request: import("@playwright/test").Request) => {
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/")) return;
    const key = `${request.method()} ${url.pathname}${url.search}`;
    requestStarted.set(request.url(), Date.now());
    apiRequests.push({ key, started: Date.now() });
  };
  const onResponse = (response: import("@playwright/test").Response) => {
    const url = new URL(response.url());
    if (!url.pathname.startsWith("/api/")) return;
    const row = [...apiRequests].reverse().find((item) => item.key === `${response.request().method()} ${url.pathname}${url.search}` && item.ended == null);
    if (row) row.ended = Date.now();
  };
  page.on("request", onRequest);
  page.on("response", onResponse);
  const bootstrap = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/bootstrap" && response.ok());
  await navigate();
  await page.locator("html[data-app-ready='true']").waitFor();
  const shellMs = Date.now() - startedAt;
  const bootstrapResponse = await bootstrap;
  const bootstrapBody = await bootstrapResponse.body();
  const mainDataReadyMs = Date.now() - startedAt;
  await delay(500);
  page.off("request", onRequest);
  page.off("response", onResponse);
  const bootstrapStarted = requestStarted.get(bootstrapResponse.url()) ?? startedAt;
  const counts = new Map<string, number>();
  for (const request of apiRequests) counts.set(request.key, (counts.get(request.key) ?? 0) + 1);
  const completed = apiRequests.filter((request) => request.ended != null);
  return {
    shellMs,
    mainDataReadyMs,
    bootstrapDurationMs: (bootstrapResponse.request().timing().responseEnd > 0)
      ? Math.round(bootstrapResponse.request().timing().responseEnd)
      : Date.now() - bootstrapStarted,
    bootstrapPayloadBytes: bootstrapBody.byteLength,
    startupRequestCount: apiRequests.length,
    duplicateRequests: [...counts.entries()].filter(([, count]) => count > 1).map(([key, count]) => `${key} x${count}`),
    apiWaterfallSpanMs: completed.length > 0
      ? Math.max(...completed.map((request) => request.ended!)) - Math.min(...completed.map((request) => request.started))
      : 0,
  };
}

test("@integration account state converges across two real devices via DB and SSE", async ({ browser }, testInfo) => {
  const firstContext = await browser.newContext();
  const secondContext = await browser.newContext();
  try {
    const first = await openLinkedDevice(firstContext, clientKeys.accountADevice1);
    const second = await openLinkedDevice(secondContext, clientKeys.accountADevice2, "/favoriten");
    await api(second, "/api/account/state");

    const preferenceStarted = Date.now();
    await api(first, "/api/account/preferences", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ notifications: { favoriteOffers: true } }),
    });
    await expect.poll(() => second.evaluate(() => {
      const state = JSON.parse(window.localStorage.getItem("lokero.state.v1") || "{}");
      return state.notifications?.favoriteOffers;
    })).toBe(true);
    const preferenceLatencyMs = Date.now() - preferenceStarted;

    await api(first, "/api/lokero/favorites/products/1", { method: "DELETE" });
    await expect.poll(() => second.evaluate(() => {
      const state = JSON.parse(window.localStorage.getItem("lokero.state.v1") || "{}");
      return state.favoriteProducts || [];
    })).not.toContain("1");

    const favoriteAddStarted = Date.now();
    await api(first, "/api/lokero/favorites/products/1", { method: "PUT" });
    await expect.poll(() => second.evaluate(() => {
      const state = JSON.parse(window.localStorage.getItem("lokero.state.v1") || "{}");
      return state.favoriteProducts || [];
    })).toContain("1");
    const favoriteAddLatencyMs = Date.now() - favoriteAddStarted;

    const alternativeState = waitForJsonResponse<{
      favoritePreferences?: Array<{ productId: string; allowAlternatives: boolean }>;
    }>(second, "/api/account/state", (state) => (
      state.favoritePreferences?.some((row) => row.productId === "1" && row.allowAlternatives) === true
    ));
    const alternativesStarted = Date.now();
    await api(first, "/api/lokero/favorites/products/1/preferences", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ allowAlternatives: true }),
    });
    await alternativeState;
    const alternativesLatencyMs = Date.now() - alternativesStarted;

    await api(first, "/api/lokero/favorites/families/cola", { method: "DELETE" });
    const familyState = waitForJsonResponse<Array<{ slug: string }>>(
      second,
      "/api/lokero/favorites/families",
      (families) => families.some((family) => family.slug === "cola"),
    );
    const productFamilyStarted = Date.now();
    await api(first, "/api/lokero/favorites/families/cola", { method: "PUT" });
    await familyState;
    const productFamilyLatencyMs = Date.now() - productFamilyStarted;

    const favoriteRemoveStarted = Date.now();
    await api(first, "/api/lokero/favorites/products/1", { method: "DELETE" });
    await expect.poll(() => second.evaluate(() => {
      const state = JSON.parse(window.localStorage.getItem("lokero.state.v1") || "{}");
      return state.favoriteProducts || [];
    })).not.toContain("1");
    const favoriteRemoveLatencyMs = Date.now() - favoriteRemoveStarted;

    await api(first, "/api/lokero/favorites/families/cola", { method: "DELETE" });

    await testInfo.attach("account-realtime-latency.json", {
      body: Buffer.from(JSON.stringify({
        preferenceLatencyMs,
        favoriteAddLatencyMs,
        favoriteRemoveLatencyMs,
        alternativesLatencyMs,
        productFamilyLatencyMs,
      }, null, 2)),
      contentType: "application/json",
    });
    console.log(`REALTIME_METRICS ${JSON.stringify({
      preferenceLatencyMs,
      favoriteAddLatencyMs,
      favoriteRemoveLatencyMs,
      alternativesLatencyMs,
      productFamilyLatencyMs,
    })}`);
  } finally {
    await firstContext.close();
    await secondContext.close();
  }
});

test("@integration shared list add, quantity, checked and reconnect converge through SSE", async ({ browser }, testInfo) => {
  const ownerContext = await browser.newContext();
  const memberContext = await browser.newContext();
  try {
    const owner = await openLinkedDevice(ownerContext, clientKeys.accountADevice1);
    const member = await openLinkedDevice(memberContext, clientKeys.accountBDevice1, "/liste");
    await expect(member.getByText("E2E Familienliste", { exact: true })).toBeVisible();
    const overview = await api<{ activeListId: string }>(owner, "/api/sharing/lists");

    const itemName = `E2E Hafermilch ${testInfo.repeatEachIndex}-${Date.now()}`;
    const reconnectName = `E2E Reconnect Kaffee ${testInfo.repeatEachIndex}-${Date.now()}`;
    const addStarted = Date.now();
    const snapshot = await api<{ items: Array<{ id: string; manualText?: string }> }>(
      owner,
      `/api/sharing/lists/${overview.activeListId}/items/manual`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ text: itemName, quantity: 1 }),
      },
    );
    await expect(member.getByText(itemName, { exact: true })).toBeVisible();
    const activeItemRow = member
      .getByRole("checkbox", { name: `${itemName} als erledigt markieren` })
      .locator("xpath=ancestor::article");
    const addLatencyMs = Date.now() - addStarted;
    const item = snapshot.items.find((row) => row.manualText === itemName);
    expect(item).toBeTruthy();

    const quantityStarted = Date.now();
    await api(owner, `/api/sharing/lists/${overview.activeListId}/items/${item!.id}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ quantity: 3 }),
    });
    await expect(activeItemRow.getByText("3 Stück", { exact: true })).toBeVisible();
    const quantityLatencyMs = Date.now() - quantityStarted;

    const checkedStarted = Date.now();
    await api(owner, `/api/sharing/lists/${overview.activeListId}/items/${item!.id}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ checked: true }),
    });
    await expect(member.getByRole("checkbox", { name: `${itemName} wieder öffnen` })).toHaveAttribute("aria-checked", "true");
    const checkedLatencyMs = Date.now() - checkedStarted;

    await memberContext.setOffline(true);
    await api(owner, `/api/sharing/lists/${overview.activeListId}/items/manual`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text: reconnectName, quantity: 1 }),
    });
    const reconnectStarted = Date.now();
    await memberContext.setOffline(false);
    await expect(member.getByText(reconnectName, { exact: true })).toBeVisible();
    const reconnectLatencyMs = Date.now() - reconnectStarted;

    await testInfo.attach("shared-list-realtime-latency.json", {
      body: Buffer.from(JSON.stringify({ addLatencyMs, quantityLatencyMs, checkedLatencyMs, reconnectLatencyMs }, null, 2)),
      contentType: "application/json",
    });
    console.log(`REALTIME_METRICS ${JSON.stringify({ addLatencyMs, quantityLatencyMs, checkedLatencyMs, reconnectLatencyMs })}`);
  } finally {
    await ownerContext.close();
    await memberContext.close();
  }
});

test("@integration concurrent two-client reads, SSE and writes do not lock SQLite", async ({ browser }) => {
  const firstContext = await browser.newContext();
  const secondContext = await browser.newContext();
  const failures: string[] = [];
  try {
    const first = await openLinkedDevice(firstContext, clientKeys.accountADevice1);
    const second = await openLinkedDevice(secondContext, clientKeys.accountADevice2);
    for (const page of [first, second]) {
      page.on("response", (response) => {
        if (response.status() >= 500) failures.push(`${response.status()} ${new URL(response.url()).pathname}`);
      });
    }
    await delay(200);
    const started = Date.now();
    const readBurst = (page: Page) => page.evaluate(async () => {
      const paths = Array.from({ length: 20 }, (_, index) => index % 2 === 0 ? "/api/account/state" : "/api/sharing/lists");
      const responses = await Promise.all(paths.map((path) => fetch(path, { credentials: "include" })));
      return responses.map((response) => response.status);
    });
    const writes = Promise.all(Array.from({ length: 10 }, (_, index) => api(
      index % 2 === 0 ? first : second,
      "/api/account/preferences",
      {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ notifications: { favoriteOffers: index % 2 === 0 } }),
      },
    )));
    const [firstStatuses, secondStatuses] = await Promise.all([readBurst(first), readBurst(second), writes]);
    expect([...firstStatuses, ...secondStatuses]).toEqual(Array(40).fill(200));
    expect(failures).toEqual([]);
    expect(Date.now() - started).toBeLessThan(10_000);

    await api(first, "/api/account/preferences", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ notifications: { favoriteOffers: true } }),
    });
    await expect.poll(() => second.evaluate(() => {
      const state = JSON.parse(window.localStorage.getItem("lokero.state.v1") || "{}");
      return state.notifications?.favoriteOffers;
    })).toBe(true);
  } finally {
    await firstContext.close();
    await secondContext.close();
  }
});

test("@integration cold and warm startup use a bounded request graph", async ({ browser }, testInfo) => {
  const context = await browser.newContext();
  try {
    await context.addCookies([
      { name: "lp_client_id", value: clientKeys.accountADevice1, domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" },
    ]);
    await context.addInitScript(() => {
      window.localStorage.setItem("spareno_onboarding_v1_completed", "1");
      window.localStorage.setItem("lokero.account.profile-id", "integration-linked");
    });
    const page = await context.newPage();
    const cold = await measureStartup(page, () => page.goto("/", { waitUntil: "domcontentloaded" }));
    const warm = await measureStartup(page, () => page.reload({ waitUntil: "domcontentloaded" }));
    const metrics = { cold, warm };
    await testInfo.attach("startup-metrics.json", {
      body: Buffer.from(JSON.stringify(metrics, null, 2)),
      contentType: "application/json",
    });
    console.log(`STARTUP_METRICS ${JSON.stringify(metrics)}`);
    expect(cold.startupRequestCount).toBeLessThanOrEqual(15);
    expect(warm.startupRequestCount).toBeLessThanOrEqual(15);
  } finally {
    await context.close();
  }
});

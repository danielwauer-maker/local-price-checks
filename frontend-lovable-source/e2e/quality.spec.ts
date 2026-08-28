import AxeBuilder from "@axe-core/playwright";
import { expect, openApp, test } from "./fixtures";

test("@critical main surfaces have no serious automated accessibility violations", async ({
  page,
}) => {
  for (const path of ["/", "/angebote", "/favoriten", "/liste", "/einstellungen", "/auth"]) {
    await openApp(page, path);
    const results = await new AxeBuilder({ page }).disableRules(["color-contrast"]).analyze();
    const critical = results.violations.filter((violation) =>
      ["critical", "serious"].includes(violation.impact ?? ""),
    );
    expect(critical, `${path}: serious/critical axe violations`).toEqual([]);
  }
});

test("responsive pages do not create horizontal overflow", async ({ page }, testInfo) => {
  test.skip(
    testInfo.project.name !== "desktop-chromium",
    "Explicit breakpoint coverage runs once.",
  );
  for (const viewport of [
    { width: 375, height: 667 },
    { width: 390, height: 844 },
    { width: 768, height: 1024 },
    { width: 1440, height: 900 },
  ]) {
    await page.setViewportSize(viewport);
    for (const path of [
      "/",
      "/angebote",
      "/favoriten",
      "/liste",
      "/auth",
      "/einstellungen",
      "/produkt/butter",
    ]) {
      await openApp(page, path);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(
        overflow,
        `${path} overflows at ${viewport.width}x${viewport.height}`,
      ).toBeLessThanOrEqual(1);
    }
  }
});

test("expected API failure degrades to deterministic preview data without blank UI", async ({
  page,
  expectServerError,
  expectConsoleError,
}) => {
  expectServerError(/503 .*\/api\/lokero\/offers/);
  expectConsoleError(/Failed to load resource/);
  await page.route("**/api/lokero/offers?*", (route) =>
    route.fulfill({ status: 503, contentType: "application/json", body: '{"detail":"offline"}' }),
  );
  await openApp(page, "/angebote");
  await page.getByRole("button", { name: /Käse/ }).click();
  await expect(page.getByText("Milbona Gouda jung").first()).toBeVisible();
});

test("PWA manifest and service worker assets are available", async ({ request }) => {
  const manifest = await request.get("/manifest.webmanifest");
  expect(manifest.ok()).toBeTruthy();
  const data = await manifest.json();
  expect(data.name).toMatch(/Spareno/i);
  expect(data.icons.length).toBeGreaterThanOrEqual(2);

  const serviceWorker = await request.get("/sw.js");
  expect(serviceWorker.ok()).toBeTruthy();
  expect(await serviceWorker.text()).not.toMatch(/cache\.addAll\(.*api/is);
});

test("auth entry points render without external credentials", async ({ page }) => {
  await openApp(page, "/auth");
  await expect(page.getByRole("textbox").first()).toBeVisible();
  await page.getByRole("button", { name: "Registrieren" }).click();
  await expect(page.getByRole("heading", { name: /Konto erstellen/i })).toBeVisible();
});

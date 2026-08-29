import { expect, openApp, test } from "./fixtures";

test("production performance baseline stays within beta-safe ceilings", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "Measured once on the reference profile.");

  const metrics: Record<string, number> = {};
  let started = Date.now();
  await openApp(page, "/");
  metrics.initialLoadMs = Date.now() - started;

  started = Date.now();
  await openApp(page, "/angebote");
  metrics.offersPageMs = Date.now() - started;

  started = Date.now();
  await openApp(page, "/produkt/butter");
  await page.getByRole("button", { name: "Als Favorit merken" }).click();
  await expect(page.getByRole("button", { name: "Favorit entfernen" })).toBeVisible();
  metrics.favoriteMutationMs = Date.now() - started;

  await testInfo.attach("performance-baseline.json", {
    body: Buffer.from(JSON.stringify(metrics, null, 2)),
    contentType: "application/json",
  });

  const measures = await page.evaluate(() => performance.getEntriesByType("measure").map((entry) => ({
    name: entry.name,
    durationMs: Math.round(entry.duration * 100) / 100,
  })));
  await testInfo.attach("spareno-performance-marks.json", {
    body: Buffer.from(JSON.stringify(measures, null, 2)),
    contentType: "application/json",
  });
  console.log(`PERFORMANCE_METRICS ${JSON.stringify(metrics)}`);

  expect(metrics.initialLoadMs).toBeLessThan(2_500);
  expect(metrics.offersPageMs).toBeLessThan(2_000);
  expect(metrics.favoriteMutationMs).toBeLessThan(3_000);
});

import { emitServerEvent, expect, openApp, test } from "./fixtures";

test("@critical shared shopping list stays optimistic and applies realtime revisions", async ({ page, apiState }) => {
  apiState.accountLinked = true;
  await openApp(page, "/liste");

  await expect(page.getByText("Familie Müller")).toBeVisible();
  await expect(page.getByText("2 Personen · Live synchronisiert")).toBeVisible();

  const butter = page.getByRole("article").filter({ hasText: "Butter mildgesäuert" });
  await butter.getByRole("button", { name: "Menge erhöhen" }).dblclick();
  await expect(butter.getByText("3", { exact: true })).toBeVisible();
  expect(apiState.sharedButterQuantity).toBe(3);

  apiState.sharedButterQuantity = 5;
  apiState.sharedRevision += 1;
  await emitServerEvent(page, "/api/sharing/lists/family-list/events", "revision", JSON.stringify({ revision: apiState.sharedRevision }));
  await expect(butter.getByText("5", { exact: true })).toBeVisible();
});

test("shopping rows only complete through the checkbox or one deliberate swipe", async ({ page, apiState }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "Touch event semantics are verified on Chromium.");
  apiState.accountLinked = true;
  await openApp(page, "/liste");

  let butter = page.getByRole("article").filter({ hasText: "Butter mildgesäuert" });
  let checkbox = butter.getByRole("checkbox", { name: "Butter mildgesäuert als erledigt markieren" });
  await expect(checkbox).toHaveAttribute("aria-checked", "false");

  await butter.dispatchEvent("click");
  await expect(checkbox).toHaveAttribute("aria-checked", "false");
  await butter.getByRole("link", { name: /Butter mildgesäuert/ }).click();
  await expect(page).toHaveURL(/\/produkt\/butter$/);
  await page.goBack();

  butter = page.getByRole("article").filter({ hasText: "Butter mildgesäuert" });
  checkbox = butter.getByRole("checkbox", { name: "Butter mildgesäuert als erledigt markieren" });
  await expect(checkbox).toHaveAttribute("aria-checked", "false");
  await checkbox.click();
  await expect(butter.getByRole("checkbox", { name: "Butter mildgesäuert wieder öffnen" })).toHaveAttribute("aria-checked", "true");
  expect(apiState.sharedButterChecked).toBe(true);

  await butter.getByRole("checkbox", { name: "Butter mildgesäuert wieder öffnen" }).click();
  const row = page.getByLabel("Offener Listeneintrag").filter({ hasText: "Butter mildgesäuert" });
  await row.dispatchEvent("touchstart", { touches: [{ identifier: 1, clientX: 20, clientY: 20 }] });
  await row.dispatchEvent("touchmove", { touches: [{ identifier: 1, clientX: 110, clientY: 22 }] });
  await row.dispatchEvent("touchend", { changedTouches: [{ identifier: 1, clientX: 110, clientY: 22 }] });
  await expect(butter.getByRole("checkbox", { name: "Butter mildgesäuert wieder öffnen" })).toHaveAttribute("aria-checked", "true");
  expect(apiState.sharedButterChecked).toBe(true);
});

test("@critical list invite preserves its return-to path through account entry", async ({ page }) => {
  await openApp(page, "/");
  await page.evaluate(() => {
    window.history.pushState({}, "", "/liste/einladung/invite-token");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await expect(page).toHaveURL(/\/liste\/einladung\/invite-token$/);
  await expect(page.getByRole("heading", { name: "Familie Müller" })).toBeVisible();
  await page.getByRole("link", { name: "Anmelden & Liste beitreten" }).click();
  await expect(page).toHaveURL(/\/auth\?returnTo=%2Fliste%2Feinladung%2Finvite-token$/);
  await expect(page.getByText("Nach der Anmeldung kommst du automatisch zu deiner Einladung zurück.")).toBeVisible();
});

test("favorite sharing exposes only selected products and public links keep return-to", async ({ page, apiState }) => {
  apiState.accountLinked = true;
  await openApp(page, "/favoriten/teilen");
  await page.getByRole("button", { name: "Favoriten-Freigabe erstellen" }).click();
  await expect(page.getByRole("switch", { name: "Favoritenliste sichtbar" })).toHaveAttribute("aria-checked", "true");
  await page.getByRole("button", { name: "Favorit verbergen" }).click();
  await expect(page.getByText("Privat", { exact: true })).toBeVisible();
  expect(apiState.sharedFavoriteVisible).toBe(false);

  apiState.sharedFavoriteVisible = true;
  await openApp(page, "/favoriten/geteilt/favorite-token");
  await expect(page.getByRole("heading", { name: "Favoriten von Daniel" })).toBeVisible();
  await expect(page.getByText("Milbona Gouda jung")).toBeVisible();
  await page.getByRole("link", { name: "Anmelden & speichern" }).click();
  await expect(page).toHaveURL(/\/auth\?returnTo=%2Ffavoriten%2Fgeteilt%2Ffavorite-token$/);
  await expect(page.getByText("Nach der Anmeldung kommst du automatisch zu den geteilten Favoriten zurück.")).toBeVisible();
});

test("friend favorites render and persist notification controls", async ({ page, apiState }) => {
  apiState.accountLinked = true;
  apiState.friendSubscribed = true;
  await openApp(page, "/favoriten/freunde");

  await expect(page.getByRole("heading", { name: "Anna" })).toBeVisible();
  await expect(page.getByText("Butter mildgesäuert")).toBeVisible();
  const inApp = page.getByRole("switch", { name: "In-App-Hinweise für Anna" });
  await expect(inApp).toHaveAttribute("aria-checked", "true");
  await inApp.click();
  await expect(inApp).toHaveAttribute("aria-checked", "false");
  expect(apiState.friendInAppEnabled).toBe(false);
});

test("@critical account realtime event reconciles remote favorites without reload", async ({ page, apiState }) => {
  apiState.accountLinked = true;
  await page.addInitScript(() => window.localStorage.setItem("lokero.account.profile-id", "17"));
  await openApp(page, "/favoriten");
  await expect(page.getByText("Milbona Gouda jung")).toBeVisible();

  apiState.accountFavoriteProducts.add("butter");
  await emitServerEvent(page, "/api/account/events", "favorites");
  await expect(page.getByText("Butter mildgesäuert")).toBeVisible();
});

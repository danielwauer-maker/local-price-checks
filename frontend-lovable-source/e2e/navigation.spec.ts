import { expect, openApp, test } from "./fixtures";

const routes = [
  ["/", "Passende Angebote zu deinen Favoriten"],
  ["/angebote", "Angebote"],
  ["/favoriten", "Favoriten"],
  ["/liste", "Liste"],
  ["/maerkte", "Märkte"],
  ["/regionen", "Regionen"],
  ["/einstellungen", "Einstellungen"],
  ["/auth", "Willkommen zurück"],
  ["/scanner", "Scanner"],
] as const;

test("@critical main routes support direct navigation and reload", async ({ page }) => {
  for (const [path, visibleText] of routes) {
    await openApp(page, path);
    await expect(page.getByText(visibleText, { exact: path !== "/" }).first()).toBeVisible();
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-app-ready", "true");
    await expect(page.locator("body")).not.toBeEmpty();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, `${path} has horizontal overflow`).toBeLessThanOrEqual(1);
  }

  await openApp(page, "/suche");
  await expect(page.getByRole("textbox", { name: "Suche" })).toBeVisible();
});

test("@critical bottom navigation and browser history remain consistent", async ({ page }) => {
  await openApp(page, "/");
  await page
    .getByRole("navigation", { name: "Hauptnavigation" })
    .getByRole("link", { name: "Märkte" })
    .click();
  await expect(page).toHaveURL(/\/maerkte$/);
  await page
    .getByRole("navigation", { name: "Hauptnavigation" })
    .getByRole("link", { name: "Favoriten" })
    .click();
  await expect(page).toHaveURL(/\/favoriten$/);
  await page.goBack();
  await expect(page).toHaveURL(/\/maerkte$/);
  await page.goForward();
  await expect(page).toHaveURL(/\/favoriten$/);
});

test("unknown routes render the application error boundary instead of a blank page", async ({
  page,
  expectConsoleError,
}) => {
  expectConsoleError(/Failed to load resource:.*404/);
  await openApp(page, "/does-not-exist");
  await expect(page.locator("body")).not.toBeEmpty();
  await expect(page.getByText(/nicht gefunden|Fehler|404/i).first()).toBeVisible();
});

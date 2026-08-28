import { expect, openApp, test } from "./fixtures";

test("@critical anonymous discovery: radius, market, search, product and back", async ({
  page,
}) => {
  await openApp(page, "/");
  await page.getByLabel("Suchradius").selectOption("20");
  await expect(page.getByLabel("Suchradius")).toHaveValue("20");

  await page
    .getByRole("navigation", { name: "Hauptnavigation" })
    .getByRole("link", { name: "Märkte" })
    .click();
  await expect(page.getByText("REWE Puderbach").first()).toBeVisible();

  await openApp(page, "/suche");
  await page.getByRole("textbox", { name: "Suche" }).fill("Butter");
  const butterResult = page.getByRole("link", { name: /Butter mildgesäuert/ });
  await expect(butterResult).toBeVisible();
  await butterResult.click();
  await expect(page).toHaveURL(/\/produkt\/butter$/);
  await expect(page.getByRole("heading", { name: "Butter mildgesäuert" })).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/\/suche/);
  await expect(page.getByRole("textbox", { name: "Suche" })).toHaveValue("Butter");
});

test("@critical favorite is optimistic, visible on favorites, and removable without navigation", async ({
  page,
}) => {
  await openApp(page, "/produkt/butter");
  const favorite = page.getByRole("button", { name: "Als Favorit merken" });
  await favorite.click();
  await expect(page.getByRole("button", { name: "Favorit entfernen" })).toBeVisible();

  await openApp(page, "/favoriten");
  await expect(page.getByText("Butter mildgesäuert")).toBeVisible();
  const remove = page
    .getByRole("button", { name: "Favorit entfernen" })
    .filter({ visible: true })
    .last();
  await remove.click();
  await expect(page.getByText("Butter mildgesäuert")).toBeHidden();
});

test("@critical rapid quantity changes are not lost and persist after reload", async ({ page }) => {
  await openApp(page, "/liste");
  const butter = page.getByRole("article").filter({ hasText: "Butter mildgesäuert" });
  await expect(butter.getByText("1", { exact: true })).toBeVisible();
  await butter.getByRole("button", { name: "Menge erhöhen" }).dblclick();
  await expect(butter.getByText("3", { exact: true })).toBeVisible();
  await page.reload();
  await expect(
    page
      .getByRole("article")
      .filter({ hasText: "Butter mildgesäuert" })
      .getByText("3", { exact: true }),
  ).toBeVisible();
});

test("adding an offer updates the shopping list immediately", async ({ page }) => {
  await openApp(page, "/angebote");
  await page.getByRole("button", { name: "Käse", exact: true }).click();
  await page
    .getByRole("button", { name: /Milbona Gouda jung zur Einkaufsliste hinzufügen/ })
    .click();
  await openApp(page, "/liste");
  await expect(page.getByText("Milbona Gouda jung").first()).toBeVisible();
});

test("product families and alternative preference persist deterministically", async ({ page }) => {
  await openApp(page, "/favoriten");
  await page.getByRole("button", { name: /Hinzufügen/ }).click();
  await page.getByRole("button", { name: /Butter/ }).click();
  await page.getByRole("button", { name: "Produktfamilie schließen" }).click();
  await expect(page.getByRole("button", { name: /Butter/ })).toBeVisible();

  const alternatives = page.getByRole("switch", { name: "Alternativen zulassen" });
  await alternatives.click();
  await expect(alternatives).toHaveAttribute("aria-checked", "true");
  await expect(page.getByText("Günstigste passende Alternative")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("switch", { name: "Alternativen zulassen" })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  await page.getByRole("switch", { name: "Alternativen zulassen" }).click();
  await expect(page.getByRole("switch", { name: "Alternativen zulassen" })).toHaveAttribute(
    "aria-checked",
    "false",
  );
  await expect(page.getByText("Günstigste passende Alternative")).toBeHidden();
  await page.getByRole("button", { name: /Butter/ }).click();
  await expect(page.getByRole("button", { name: /Butter/ })).toBeHidden();
});

test("quantity zero removes an item and the empty list survives reload", async ({ page }) => {
  await openApp(page, "/liste");
  const butter = page.getByRole("article").filter({ hasText: "Butter mildgesäuert" });
  await butter.getByRole("button", { name: "Menge verringern" }).click();
  await expect(page.getByText("Deine Einkaufsliste ist noch leer.")).toBeVisible();
  await page.reload();
  await expect(page.getByText("Deine Einkaufsliste ist noch leer.")).toBeVisible();
});

test("market favorites update optimistically and persist", async ({ page }) => {
  await openApp(page, "/maerkte");
  const aldi = page.getByRole("article").filter({ hasText: "ALDI" }).first();
  await aldi.getByRole("button", { name: "Markt zu Favoriten" }).click();
  await expect(aldi.getByRole("button", { name: "Markt aus Favoriten entfernen" })).toBeVisible();
  await page.reload();
  await expect(
    page
      .getByRole("article")
      .filter({ hasText: "ALDI" })
      .first()
      .getByRole("button", { name: "Markt aus Favoriten entfernen" }),
  ).toBeVisible();
});

test("settings survive reload", async ({ page }) => {
  await openApp(page, "/einstellungen");
  await page.getByRole("button", { name: "20 km" }).click();
  const travelCost = page.getByRole("spinbutton");
  await travelCost.fill("0.42");
  await travelCost.blur();
  await page.getByRole("switch", { name: "Neue Angebote" }).click();
  await page.reload();
  await expect(page.getByRole("spinbutton")).toHaveValue("0.42");
  await expect(page.getByRole("switch", { name: "Neue Angebote" })).toHaveAttribute(
    "aria-checked",
    "false",
  );
});

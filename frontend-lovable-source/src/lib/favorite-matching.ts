import type { Product } from "@/data/demo";

function normalize(value: string) {
  return value
    .toLocaleLowerCase("de-DE")
    .normalize("NFKD")
    .replace(/[®™]/g, "")
    .replace(/[^a-z0-9äöüß]+/g, " ")
    .replace(/\b\d+(?:[.,]\d+)?\s*(?:g|kg|ml|l|liter|stk|stück|rollen|wl)\b/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function exactKey(product: Product) {
  return `${normalize(product.brand || "")}::${normalize(product.name)}`;
}

const FAMILY_RULES: Array<{ key: string; terms: RegExp[] }> = [
  { key: "cola", terms: [/\bcola\b/, /\bkola\b/, /\bcoca cola\b/, /\bpepsi\b/, /\bfreeway\b.*\bcola\b/, /\briver\b.*\bcola\b/] },
  { key: "orange-lemonade", terms: [/\borangenlimonade\b/, /\borange limonade\b/, /\bfanta orange\b/, /\borangina\b/] },
  { key: "lemon-lime", terms: [/\bzitrone limette\b/, /\blemon lime\b/, /\bsprite\b/, /\b7up\b/, /\b7 up\b/] },
  { key: "mineral-water", terms: [/\bmineralwasser\b/, /\btafelwasser\b/] },
  { key: "butter", terms: [/\bbutter\b/, /\bkaergarden\b/, /\bkærgarden\b/] },
  { key: "coffee", terms: [/\bkaffee\b/, /\bcaffe crema\b/, /\bcaffè crema\b/, /\bfilterkaffee\b/] },
  { key: "yogurt", terms: [/\bjoghurt\b/, /\byoghurt\b/] },
  { key: "milk", terms: [/\bvollmilch\b/, /\bmilch\b/] },
  { key: "potato-chips", terms: [/\bchips\b/, /\briffels\b/, /\bpom bär\b/, /\bpombär\b/] },
  { key: "laundry-detergent", terms: [/\bwaschmittel\b/, /\bvollwaschmittel\b/, /\bcolorwaschmittel\b/] },
  { key: "toilet-paper", terms: [/\btoilettenpapier\b/, /\bklopapier\b/] },
];

export function favoriteFamilyKey(product: Product): string | null {
  const haystack = normalize(`${product.brand || ""} ${product.name}`);
  return FAMILY_RULES.find((rule) => rule.terms.some((term) => term.test(haystack)))?.key ?? null;
}

export function hasAlternativeFamily(product: Product) {
  return favoriteFamilyKey(product) !== null;
}

export function matchesFavorite(favorite: Product, candidate: Product, allowAlternatives: boolean) {
  if (exactKey(favorite) === exactKey(candidate)) return true;
  if (!allowAlternatives) return false;
  const favoriteFamily = favoriteFamilyKey(favorite);
  return favoriteFamily !== null && favoriteFamily === favoriteFamilyKey(candidate);
}

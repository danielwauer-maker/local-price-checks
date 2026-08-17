export type Market = {
  id: string;
  name: string;
  chain: string;
  street: string;
  city: string;
  lat: number;
  lng: number;
  openUntil: string;
  rating: number;
};

export type Product = {
  id: string;
  name: string;
  brand: string;
  category: Category;
  unit: string;
  ean: string;
  emoji: string;
};

export type Category =
  | "Molkerei"
  | "Obst & Gemüse"
  | "Fleisch & Fisch"
  | "Getränke"
  | "Grundnahrung"
  | "Süsses & Snacks"
  | "Haushalt";

export type Price = {
  productId: string;
  marketId: string;
  price: number;
  /** Reduzierter Angebotspreis, falls aktuell im Prospekt */
  offer?: { price: number; until: string };
};

export const CATEGORIES: Category[] = [
  "Molkerei",
  "Obst & Gemüse",
  "Fleisch & Fisch",
  "Getränke",
  "Grundnahrung",
  "Süsses & Snacks",
  "Haushalt",
];

/** Referenzstandort (Dierdorf / Westerwald) – wird ohne GPS genutzt. */
export const DEFAULT_LOCATION = { lat: 50.5497, lng: 7.6558, label: "56269 Dierdorf" };

export const MARKETS: Market[] = [
  {
    id: "rewe-hundertmark",
    name: "REWE XL Hundertmark",
    chain: "REWE",
    street: "Marktstraße 14",
    city: "Dierdorf",
    lat: 50.5512,
    lng: 7.6601,
    openUntil: "21:00",
    rating: 4.4,
  },
  {
    id: "aldi-dierdorf",
    name: "ALDI SÜD Dierdorf",
    chain: "ALDI SÜD",
    street: "Koblenzer Str. 2",
    city: "Dierdorf",
    lat: 50.5464,
    lng: 7.6489,
    openUntil: "20:00",
    rating: 4.1,
  },
  {
    id: "lidl-dierdorf",
    name: "Lidl Dierdorf",
    chain: "Lidl",
    street: "Am Hallenbad 5",
    city: "Dierdorf",
    lat: 50.5551,
    lng: 7.6437,
    openUntil: "21:00",
    rating: 4.2,
  },
  {
    id: "edeka-puderbach",
    name: "EDEKA Wagner",
    chain: "EDEKA",
    street: "Hauptstraße 41",
    city: "Puderbach",
    lat: 50.6011,
    lng: 7.5719,
    openUntil: "20:00",
    rating: 4.6,
  },
  {
    id: "penny-selters",
    name: "PENNY Selters",
    chain: "PENNY",
    street: "Rheinstraße 9",
    city: "Selters",
    lat: 50.5259,
    lng: 7.7462,
    openUntil: "20:00",
    rating: 3.9,
  },
  {
    id: "netto-neuwied",
    name: "Netto Marken-Discount",
    chain: "Netto",
    street: "Andernacher Str. 88",
    city: "Neuwied",
    lat: 50.4361,
    lng: 7.4708,
    openUntil: "21:00",
    rating: 4.0,
  },
];

export const PRODUCTS: Product[] = [
  { id: "p1", name: "Almighurt Erdbeere", brand: "Ehrmann", category: "Molkerei", unit: "150 g", ean: "4002971000108", emoji: "🍓" },
  { id: "p2", name: "Frische Vollmilch 3,5%", brand: "Weihenstephan", category: "Molkerei", unit: "1 l", ean: "4008878100119", emoji: "🥛" },
  { id: "p3", name: "Butter mildgesäuert", brand: "Kerrygold", category: "Molkerei", unit: "250 g", ean: "5011038001155", emoji: "🧈" },
  { id: "p4", name: "Gouda jung in Scheiben", brand: "Frico", category: "Molkerei", unit: "200 g", ean: "8712100845123", emoji: "🧀" },
  { id: "p5", name: "Bananen", brand: "Chiquita", category: "Obst & Gemüse", unit: "1 kg", ean: "4011200296908", emoji: "🍌" },
  { id: "p6", name: "Äpfel Elstar", brand: "Regional", category: "Obst & Gemüse", unit: "1 kg", ean: "2000000000015", emoji: "🍎" },
  { id: "p7", name: "Rispentomaten", brand: "Regional", category: "Obst & Gemüse", unit: "500 g", ean: "2000000000022", emoji: "🍅" },
  { id: "p8", name: "Speisekartoffeln festkochend", brand: "Regional", category: "Obst & Gemüse", unit: "2,5 kg", ean: "2000000000039", emoji: "🥔" },
  { id: "p9", name: "Hähnchenbrustfilet", brand: "Wiesenhof", category: "Fleisch & Fisch", unit: "400 g", ean: "4002566110024", emoji: "🍗" },
  { id: "p10", name: "Rinderhackfleisch", brand: "Metzgerfrisch", category: "Fleisch & Fisch", unit: "500 g", ean: "2000000000046", emoji: "🥩" },
  { id: "p11", name: "Lachsfilet TK", brand: "Followfish", category: "Fleisch & Fisch", unit: "250 g", ean: "4260081720014", emoji: "🐟" },
  { id: "p12", name: "Mineralwasser Classic", brand: "Gerolsteiner", category: "Getränke", unit: "6×1 l", ean: "4001513000123", emoji: "💧" },
  { id: "p13", name: "Orangensaft 100%", brand: "Hohes C", category: "Getränke", unit: "1 l", ean: "4008100210103", emoji: "🍊" },
  { id: "p14", name: "Cola Zero", brand: "Coca-Cola", category: "Getränke", unit: "1,25 l", ean: "5000112637922", emoji: "🥤" },
  { id: "p15", name: "Filterkaffee Gold", brand: "Dallmayr", category: "Getränke", unit: "500 g", ean: "4008167010005", emoji: "☕" },
  { id: "p16", name: "Spaghetti No. 5", brand: "Barilla", category: "Grundnahrung", unit: "500 g", ean: "8076809513753", emoji: "🍝" },
  { id: "p17", name: "Basmati Reis", brand: "Oryza", category: "Grundnahrung", unit: "1 kg", ean: "4002676100113", emoji: "🍚" },
  { id: "p18", name: "Weizenmehl Type 405", brand: "Aurora", category: "Grundnahrung", unit: "1 kg", ean: "4000675100114", emoji: "🌾" },
  { id: "p19", name: "Die Ofenfrische Vier Käse", brand: "Dr. Oetker", category: "Grundnahrung", unit: "410 g", ean: "4001724819400", emoji: "🍕" },
  { id: "p20", name: "Alpenmilch Schokolade", brand: "Milka", category: "Süsses & Snacks", unit: "100 g", ean: "7622210447326", emoji: "🍫" },
  { id: "p21", name: "Paprika Chips", brand: "funny-frisch", category: "Süsses & Snacks", unit: "150 g", ean: "4001242000141", emoji: "🥔" },
  { id: "p22", name: "Milchreis Klassik", brand: "Müller", category: "Süsses & Snacks", unit: "200 g", ean: "4025500110024", emoji: "🍮" },
  { id: "p23", name: "Toilettenpapier 3-lagig", brand: "Zewa", category: "Haushalt", unit: "10 Rollen", ean: "7322540000108", emoji: "🧻" },
  { id: "p24", name: "Vollwaschmittel", brand: "Persil", category: "Haushalt", unit: "20 WL", ean: "4015000000123", emoji: "🧴" },
];

const BASE_PRICE: Record<string, number> = {
  p1: 0.45, p2: 1.29, p3: 2.79, p4: 2.19, p5: 1.69, p6: 2.49, p7: 1.99, p8: 3.49,
  p9: 5.49, p10: 4.29, p11: 4.99, p12: 4.29, p13: 1.99, p14: 1.39, p15: 6.99,
  p16: 1.49, p17: 2.99, p18: 0.89, p19: 3.29, p20: 1.49, p21: 1.79, p22: 0.59,
  p23: 4.99, p24: 4.49,
};

/** Preisniveau je Markt (Discounter günstiger) */
const MARKET_FACTOR: Record<string, number> = {
  "rewe-hundertmark": 1.08,
  "aldi-dierdorf": 0.9,
  "lidl-dierdorf": 0.92,
  "edeka-puderbach": 1.12,
  "penny-selters": 0.96,
  "netto-neuwied": 0.94,
};

/** Deterministisches Pseudo-Rauschen, damit Preise ohne Backend stabil bleiben. */
function jitter(seed: string) {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) % 9973;
  return 0.93 + (h % 15) / 100; // 0.93 – 1.07
}

const OFFER_UNTIL = "22.08.";

/** Angebote (Produkt → Markt) mit Rabattfaktor */
const OFFERS: Array<[string, string, number]> = [
  ["p1", "rewe-hundertmark", 0.55],
  ["p19", "rewe-hundertmark", 0.68],
  ["p22", "rewe-hundertmark", 0.6],
  ["p20", "lidl-dierdorf", 0.66],
  ["p9", "lidl-dierdorf", 0.72],
  ["p5", "aldi-dierdorf", 0.7],
  ["p12", "aldi-dierdorf", 0.75],
  ["p15", "aldi-dierdorf", 0.71],
  ["p3", "netto-neuwied", 0.7],
  ["p10", "netto-neuwied", 0.74],
  ["p23", "penny-selters", 0.65],
  ["p14", "penny-selters", 0.69],
  ["p7", "edeka-puderbach", 0.7],
  ["p11", "edeka-puderbach", 0.73],
  ["p21", "lidl-dierdorf", 0.62],
  ["p16", "netto-neuwied", 0.67],
];

const offerMap = new Map(OFFERS.map(([p, m, f]) => [`${p}:${m}`, f]));

export const PRICES: Price[] = PRODUCTS.flatMap((product) =>
  MARKETS.map((market) => {
    const raw = BASE_PRICE[product.id]! * MARKET_FACTOR[market.id]! * jitter(product.id + market.id);
    const price = Math.round(raw * 100) / 100;
    const factor = offerMap.get(`${product.id}:${market.id}`);
    return {
      productId: product.id,
      marketId: market.id,
      price,
      ...(factor
        ? { offer: { price: Math.round(price * factor * 100) / 100, until: OFFER_UNTIL } }
        : {}),
    } satisfies Price;
  }),
);

const priceIndex = new Map(PRICES.map((p) => [`${p.productId}:${p.marketId}`, p]));

export function getPrice(productId: string, marketId: string): Price | undefined {
  return priceIndex.get(`${productId}:${marketId}`);
}

export function effectivePrice(p: Price): number {
  return p.offer ? p.offer.price : p.price;
}

export function getProduct(id: string): Product | undefined {
  return PRODUCTS.find((p) => p.id === id);
}

export function getMarket(id: string): Market | undefined {
  return MARKETS.find((m) => m.id === id);
}

export function formatEuro(value: number): string {
  return value.toLocaleString("de-DE", { style: "currency", currency: "EUR" });
}

/** Luftlinie in km */
export function distanceKm(
  a: { lat: number; lng: number },
  b: { lat: number; lng: number },
): number {
  const R = 6371;
  const dLat = ((b.lat - a.lat) * Math.PI) / 180;
  const dLng = ((b.lng - a.lng) * Math.PI) / 180;
  const lat1 = (a.lat * Math.PI) / 180;
  const lat2 = (b.lat * Math.PI) / 180;
  const h =
    Math.sin(dLat / 2) ** 2 + Math.sin(dLng / 2) ** 2 * Math.cos(lat1) * Math.cos(lat2);
  return Math.round(2 * R * Math.asin(Math.sqrt(h)) * 10) / 10;
}

export type OfferItem = { product: Product; market: Market; price: Price; discount: number };

export function currentOffers(marketIds?: string[]): OfferItem[] {
  return PRICES.filter((p) => p.offer)
    .filter((p) => !marketIds || marketIds.length === 0 || marketIds.includes(p.marketId))
    .map((p) => ({
      product: getProduct(p.productId)!,
      market: getMarket(p.marketId)!,
      price: p,
      discount: Math.round((1 - p.offer!.price / p.price) * 100),
    }))
    .sort((a, b) => b.discount - a.discount);
}

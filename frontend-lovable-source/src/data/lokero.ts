/**
 * Lokero Mock-/Fallbackdaten für die Preview.
 *
 * WICHTIG: Diese Datei ist reine Datenhaltung für die Vorschau. Die UI greift
 * ausschliesslich über `src/services/lokero-api.ts` darauf zu, damit später
 * die echten Backend-Endpunkte eingehängt werden können.
 */

export type CategoryId =
  | "obst-gemuese"
  | "fleisch-wurst"
  | "fisch"
  | "kaese"
  | "molkerei"
  | "brot"
  | "getraenke"
  | "alkohol"
  | "suesswaren"
  | "tiefkuehl"
  | "vorrat"
  | "nudeln-reis"
  | "kochen-wuerzen"
  | "fruehstueck"
  | "fertiggerichte"
  | "vegetarisch-vegan"
  | "baby-kind"
  | "drogerie"
  | "haushalt"
  | "tiernahrung"
  | "non-food"
  | "sonstiges";

export type DietTag = "vegan" | "vegetarisch" | "glutenfrei" | "bio";

export type Category = {
  id: CategoryId;
  label: string;
  /** Lucide Icon-Key, siehe components/CategoryIcon.tsx */
  icon: string;
  synonyms: string[];
};

export const CATEGORIES: Category[] = [
  { id: "obst-gemuese", label: "Obst & Gemüse", icon: "apple", synonyms: ["obst", "gemüse", "salat", "banane"] },
  { id: "fleisch-wurst", label: "Fleisch & Wurst", icon: "beef", synonyms: ["fleisch", "wurst", "hack", "schnitzel"] },
  { id: "fisch", label: "Fisch & Meeresfrüchte", icon: "fish", synonyms: ["fisch", "lachs", "thunfisch", "meeresfrüchte", "fischstäbchen"] },
  { id: "kaese", label: "Käse", icon: "cheese", synonyms: ["käse", "gouda", "mozzarella"] },
  { id: "molkerei", label: "Milch & Molkerei", icon: "milk", synonyms: ["milch", "joghurt", "quark", "butter"] },
  { id: "brot", label: "Brot & Backwaren", icon: "bread", synonyms: ["brot", "brötchen", "toast"] },
  { id: "getraenke", label: "Getränke", icon: "drink", synonyms: ["getränk", "cola", "wasser", "saft"] },
  { id: "alkohol", label: "Alkoholische Getränke", icon: "drink", synonyms: ["bier", "wein", "sekt", "spirituosen"] },
  { id: "suesswaren", label: "Süßwaren & Snacks", icon: "candy", synonyms: ["schokolade", "chips", "snack"] },
  { id: "tiefkuehl", label: "Tiefkühl", icon: "snow", synonyms: ["tiefkühl", "tk", "pizza", "fischstäbchen"] },
  { id: "vorrat", label: "Vorrat", icon: "wheat", synonyms: ["nudeln", "reis", "mehl", "konserve"] },
  { id: "nudeln-reis", label: "Nudeln, Reis & Beilagen", icon: "wheat", synonyms: ["nudeln", "reis", "pasta"] },
  { id: "kochen-wuerzen", label: "Kochen & Würzen", icon: "soup", synonyms: ["öl", "essig", "gewürze", "sauce"] },
  { id: "fruehstueck", label: "Frühstück", icon: "coffee", synonyms: ["müsli", "kaffee", "marmelade"] },
  { id: "fertiggerichte", label: "Fertiggerichte", icon: "soup", synonyms: ["fertig", "suppe"] },
  { id: "vegetarisch-vegan", label: "Vegetarisch & Vegan", icon: "apple", synonyms: ["vegan", "vegetarisch", "pflanzlich"] },
  { id: "baby-kind", label: "Baby & Kind", icon: "package", synonyms: ["baby", "windeln", "babynahrung"] },
  { id: "drogerie", label: "Drogerie", icon: "sparkles", synonyms: ["shampoo", "zahnpasta"] },
  { id: "haushalt", label: "Haushalt", icon: "home", synonyms: ["papier", "waschmittel", "reiniger"] },
  { id: "tiernahrung", label: "Tiernahrung", icon: "package", synonyms: ["katzenfutter", "hundefutter"] },
  { id: "non-food", label: "Non-Food", icon: "package", synonyms: ["haushaltswaren", "zubehör"] },
  { id: "sonstiges", label: "Sonstiges", icon: "package", synonyms: [] },
];

/** Chips auf dem Startscreen (Reihenfolge wie im Design). */
export const HOME_CATEGORY_IDS: CategoryId[] = [
  "obst-gemuese",
  "fleisch-wurst",
  "kaese",
  "fisch",
  "getraenke",
];

export type Chain = "REWE" | "Lidl" | "ALDI SÜD" | "Netto" | "EDEKA";

export type Market = {
  id: string;
  name: string;
  chain: Chain;
  street: string;
  city: string;
  lat: number;
  lng: number;
  openUntil: string;
  isOpen: boolean;
  distanceKm: number;
  /** Vom Backend geliefertes Sparpotenzial bezogen auf die aktuelle Liste */
  savingPotential: number;
  strength: string;
};

export const DEFAULT_LOCATION = { lat: 50.6011, lng: 7.5719, label: "Steimel / Puderbach" };

export const MARKETS: Market[] = [
  {
    id: "rewe-puderbach",
    name: "REWE Puderbach",
    chain: "REWE",
    street: "Hauptstraße 41",
    city: "Puderbach",
    lat: 50.6034,
    lng: 7.5771,
    openUntil: "22:00",
    isOpen: true,
    distanceKm: 1.2,
    savingPotential: 12.4,
    strength: "Gut für Fleisch & Frische",
  },
  {
    id: "lidl-puderbach",
    name: "Lidl Puderbach",
    chain: "Lidl",
    street: "Am Hallenbad 5",
    city: "Puderbach",
    lat: 50.5966,
    lng: 7.5652,
    openUntil: "21:30",
    isOpen: true,
    distanceKm: 1.5,
    savingPotential: 9.8,
    strength: "Gut für Getränke & Snacks",
  },
  {
    id: "aldi-dierdorf",
    name: "ALDI SÜD Dierdorf",
    chain: "ALDI SÜD",
    street: "Koblenzer Str. 2",
    city: "Dierdorf",
    lat: 50.5721,
    lng: 7.6032,
    openUntil: "20:00",
    isOpen: true,
    distanceKm: 3.8,
    savingPotential: 7.3,
    strength: "Gut für Basics & Haushaltswaren",
  },
  {
    id: "netto-raubach",
    name: "Netto Marken-Discount",
    chain: "Netto",
    street: "Rheinstraße 9",
    city: "Raubach",
    lat: 50.5847,
    lng: 7.5468,
    openUntil: "21:00",
    isOpen: true,
    distanceKm: 4.1,
    savingPotential: 4.1,
    strength: "Gut für Süßes & Snacks",
  },
  {
    id: "edeka-puderbach",
    name: "EDEKA Puderbach",
    chain: "EDEKA",
    street: "Marktstraße 14",
    city: "Puderbach",
    lat: 50.6108,
    lng: 7.5839,
    openUntil: "20:00",
    isOpen: true,
    distanceKm: 4.3,
    savingPotential: 3.6,
    strength: "Gut für Obst & Gemüse",
  },
];

export type Product = {
  id: string;
  name: string;
  brand: string;
  amount: string;
  detail?: string;
  category: CategoryId;
  ean: string;
  tags: DietTag[];
};

export type Offer = {
  productId: string;
  marketId: string;
  price: number;
  oldPrice?: number;
  discount?: number;
  /** Grundpreis-Text, z. B. "1 kg = 6,76 €" */
  basePrice?: string;
  leafletPage?: number;
  validFrom: string;
  validUntil: string;
};

export const PRODUCTS: Product[] = [
  { id: "gouda-milbona", name: "Milbona Gouda jung", brand: "Milbona", amount: "250 g", detail: "45 % Fett i. Tr., 250 g", category: "kaese", ean: "20123451", tags: ["vegetarisch", "glutenfrei"] },
  { id: "gouda-goldsteig", name: "Goldsteig Gouda", brand: "Goldsteig", amount: "250 g", detail: "48 % Fett i. Tr., 250 g", category: "kaese", ean: "20123452", tags: ["vegetarisch", "glutenfrei"] },
  { id: "hack-gemischt", name: "Hackfleisch gemischt", brand: "Wilhelm Brandenburg", amount: "500 g", detail: "Rind & Schwein, 500 g", category: "fleisch-wurst", ean: "20123453", tags: ["glutenfrei"] },
  { id: "alpro-hafer", name: "Alpro Haferdrink", brand: "Alpro", amount: "1 l", detail: "Haferdrink Original, 1 l", category: "molkerei", ean: "20123454", tags: ["vegan", "glutenfrei"] },
  { id: "iglo-fischstaebchen", name: "Iglo Fischstäbchen", brand: "Iglo", amount: "450 g", detail: "15 Stück, 450 g", category: "tiefkuehl", ean: "20123455", tags: [] },
  { id: "coca-cola-15", name: "Coca-Cola Original", brand: "Coca-Cola", amount: "1,5 l", detail: "1,5 l zzgl. Pfand", category: "getraenke", ean: "20123456", tags: ["vegan", "glutenfrei"] },
  { id: "pepsi-15", name: "Pepsi Cola", brand: "Pepsi", amount: "1,5 l", detail: "1,5 l zzgl. Pfand", category: "getraenke", ean: "20123457", tags: ["vegan", "glutenfrei"] },
  { id: "freeway-cola", name: "Freeway Cola", brand: "Freeway", amount: "1,5 l", detail: "1,5 l zzgl. Pfand", category: "getraenke", ean: "20123458", tags: ["vegan", "glutenfrei"] },
  { id: "lachsfilet", name: "Lachsfilet", brand: "Frische Theke", amount: "100 g", detail: "Frisch, 100 g", category: "fisch", ean: "20123459", tags: ["glutenfrei"] },
  { id: "lachsfilet-asc", name: "ASC Lachsfilet", brand: "ASC", amount: "100 g", detail: "Zuchtlachs ASC, 100 g", category: "fisch", ean: "20123460", tags: ["glutenfrei"] },
  { id: "vollmilch", name: "Frische Vollmilch 3,5 %", brand: "Weihenstephan", amount: "1 l", category: "molkerei", ean: "20123461", tags: ["vegetarisch", "glutenfrei"] },
  { id: "bananen", name: "Bananen", brand: "Chiquita", amount: "1 kg", category: "obst-gemuese", ean: "20123462", tags: ["vegan", "glutenfrei", "bio"] },
  { id: "joghurt-natur", name: "Joghurt mild", brand: "Milbona", amount: "500 g", category: "molkerei", ean: "20123463", tags: ["vegetarisch", "glutenfrei"] },
  { id: "butter", name: "Butter mildgesäuert", brand: "Kerrygold", amount: "250 g", category: "molkerei", ean: "20123464", tags: ["vegetarisch", "glutenfrei"] },
  { id: "spaghetti", name: "Spaghetti No. 5", brand: "Barilla", amount: "500 g", category: "vorrat", ean: "20123465", tags: ["vegan"] },
  { id: "thunfisch", name: "Thunfisch in eigenem Saft", brand: "Followfish", amount: "185 g", category: "fisch", ean: "20123466", tags: ["glutenfrei"] },
  { id: "raeucherlachs", name: "Räucherlachs", brand: "Ostsee", amount: "100 g", category: "fisch", ean: "20123467", tags: ["glutenfrei"] },
  { id: "haehnchenbrust", name: "Hähnchenbrustfilet", brand: "Wiesenhof", amount: "400 g", category: "fleisch-wurst", ean: "20123468", tags: ["glutenfrei"] },
  { id: "toilettenpapier", name: "Toilettenpapier 3-lagig", brand: "Zewa", amount: "10 Rollen", category: "haushalt", ean: "20123469", tags: [] },
  { id: "mineralwasser", name: "Mineralwasser Classic", brand: "Gerolsteiner", amount: "6 × 1 l", category: "getraenke", ean: "20123470", tags: ["vegan", "glutenfrei"] },
  { id: "toastbrot", name: "Buttertoast", brand: "Golden Toast", amount: "500 g", category: "brot", ean: "20123471", tags: ["vegetarisch"] },
  { id: "kaffee", name: "Filterkaffee Gold", brand: "Dallmayr", amount: "500 g", category: "fruehstueck", ean: "20123472", tags: ["vegan", "glutenfrei"] },
];

const WEEK_FROM = "2025-05-13";
const WEEK_UNTIL = "2025-05-19";

export const OFFER_WEEK = { from: WEEK_FROM, until: WEEK_UNTIL };

export const OFFERS: Offer[] = [
  { productId: "gouda-milbona", marketId: "lidl-puderbach", price: 1.69, oldPrice: 2.19, discount: 23, basePrice: "1 kg = 6,76 €", leafletPage: 12, validFrom: WEEK_FROM, validUntil: WEEK_UNTIL },
  { productId: "hack-gemischt", marketId: "rewe-puderbach", price: 3.99, oldPrice: 4.99, discount: 20, basePrice: "1 kg = 7,98 €", leafletPage: 4, validFrom: WEEK_FROM, validUntil: WEEK_UNTIL },
  { productId: "alpro-hafer", marketId: "lidl-puderbach", price: 1.49, oldPrice: 1.99, discount: 25, basePrice: "1 l = 1,49 €", leafletPage: 16, validFrom: WEEK_FROM, validUntil: WEEK_UNTIL },
  { productId: "iglo-fischstaebchen", marketId: "edeka-puderbach", price: 2.79, oldPrice: 3.99, discount: 30, basePrice: "1 kg = 6,20 €", leafletPage: 20, validFrom: WEEK_FROM, validUntil: WEEK_UNTIL },
  { productId: "coca-cola-15", marketId: "netto-raubach", price: 0.99, oldPrice: 1.29, discount: 23, basePrice: "1 l = 0,66 €", leafletPage: 22, validFrom: WEEK_FROM, validUntil: WEEK_UNTIL },
];

export type MarketPrice = { productId: string; marketId: string; price: number };
export const MARKET_PRICES: MarketPrice[] = [
  { productId: "gouda-milbona", marketId: "lidl-puderbach", price: 1.69 },
  { productId: "gouda-milbona", marketId: "rewe-puderbach", price: 1.99 },
  { productId: "coca-cola-15", marketId: "lidl-puderbach", price: 0.99 },
  { productId: "coca-cola-15", marketId: "rewe-puderbach", price: 1.09 },
  { productId: "alpro-hafer", marketId: "lidl-puderbach", price: 1.49 },
  { productId: "lachsfilet", marketId: "rewe-puderbach", price: 2.29 },
  { productId: "vollmilch", marketId: "lidl-puderbach", price: 1.09 },
  { productId: "bananen", marketId: "lidl-puderbach", price: 1.49 },
  { productId: "joghurt-natur", marketId: "lidl-puderbach", price: 0.89 },
  { productId: "butter", marketId: "rewe-puderbach", price: 2.49 },
  { productId: "spaghetti", marketId: "lidl-puderbach", price: 1.19 },
  { productId: "haehnchenbrust", marketId: "rewe-puderbach", price: 4.49 },
  { productId: "toastbrot", marketId: "lidl-puderbach", price: 1.49 },
  { productId: "kaffee", marketId: "lidl-puderbach", price: 5.99 },
  { productId: "toilettenpapier", marketId: "rewe-puderbach", price: 3.99 },
  { productId: "mineralwasser", marketId: "rewe-puderbach", price: 4.49 },
  { productId: "thunfisch", marketId: "rewe-puderbach", price: 1.89 },
  { productId: "raeucherlachs", marketId: "rewe-puderbach", price: 2.49 },
];

export type AlternativeKind = "identisch" | "marke" | "eigenmarke" | "aehnlich";
export type Alternative = {
  productId: string;
  alternativeProductId: string;
  kind: AlternativeKind;
  price: number;
  marketId: string;
};

export const ALTERNATIVES: Alternative[] = [
  { productId: "gouda-milbona", alternativeProductId: "gouda-goldsteig", kind: "marke", price: 1.69, marketId: "rewe-puderbach" },
  { productId: "coca-cola-15", alternativeProductId: "pepsi-15", kind: "marke", price: 0.89, marketId: "lidl-puderbach" },
  { productId: "coca-cola-15", alternativeProductId: "freeway-cola", kind: "eigenmarke", price: 0.79, marketId: "lidl-puderbach" },
  { productId: "lachsfilet", alternativeProductId: "lachsfilet-asc", kind: "aehnlich", price: 2.09, marketId: "rewe-puderbach" },
];

export type FavoriteProduct = {
  productId: string;
  marketId: string;
  price: number;
};

export const FAVORITE_PRODUCTS: FavoriteProduct[] = [
  { productId: "gouda-milbona", marketId: "lidl-puderbach", price: 1.79 },
  { productId: "coca-cola-15", marketId: "lidl-puderbach", price: 0.99 },
  { productId: "alpro-hafer", marketId: "lidl-puderbach", price: 1.49 },
  { productId: "lachsfilet", marketId: "rewe-puderbach", price: 2.29 },
];

export const FAVORITE_MARKET_IDS = ["lidl-puderbach", "rewe-puderbach"];

export type PriceAlert = {
  productId: string;
  targetPrice: number;
  currentPrice: number;
  marketId: string;
  active: boolean;
};

export const PRICE_ALERTS: PriceAlert[] = [
  { productId: "alpro-hafer", targetPrice: 1.29, currentPrice: 1.49, marketId: "lidl-puderbach", active: true },
  { productId: "coca-cola-15", targetPrice: 0.89, currentPrice: 0.99, marketId: "netto-raubach", active: false },
];

export type ShoppingListItem = {
  productId: string;
  qty: number;
};

export const DEFAULT_LIST: ShoppingListItem[] = [
  { productId: "vollmilch", qty: 2 },
  { productId: "coca-cola-15", qty: 2 },
  { productId: "bananen", qty: 1 },
  { productId: "joghurt-natur", qty: 2 },
  { productId: "butter", qty: 1 },
  { productId: "gouda-milbona", qty: 1 },
  { productId: "hack-gemischt", qty: 1 },
  { productId: "haehnchenbrust", qty: 1 },
  { productId: "spaghetti", qty: 2 },
  { productId: "alpro-hafer", qty: 1 },
  { productId: "lachsfilet", qty: 2 },
  { productId: "toastbrot", qty: 1 },
  { productId: "kaffee", qty: 1 },
];

/**
 * Optimierter Einkauf – kommt später 1:1 vom Backend
 * (Sparplan-, Routen- und Fahrtkostenberechnung liegen NICHT im Frontend).
 */
export type OptimizedStop = {
  marketId: string;
  total: number;
  itemCount: number;
  productIds: string[];
};

export type OptimizedTrip = {
  itemCount: number;
  total: number;
  savings: number;
  travelCost: number;
  stops: OptimizedStop[];
  distanceKm: number;
  combinationLabel: string;
  savingsExplanation: string;
};

export const OPTIMIZED_TRIP: OptimizedTrip = {
  itemCount: 18,
  total: 27.85,
  savings: 8.42,
  travelCost: 3.6,
  distanceKm: 8.2,
  combinationLabel: "Lidl + REWE",
  savingsExplanation: "Verglichen mit dem günstigsten Einkauf bei nur einem Markt.",
  stops: [
    {
      marketId: "lidl-puderbach",
      total: 12.87,
      itemCount: 9,
      productIds: ["vollmilch", "coca-cola-15", "bananen", "joghurt-natur", "gouda-milbona", "alpro-hafer", "toastbrot", "kaffee", "spaghetti"],
    },
    {
      marketId: "rewe-puderbach",
      total: 14.98,
      itemCount: 9,
      productIds: ["hack-gemischt", "haehnchenbrust", "lachsfilet", "butter", "toilettenpapier", "mineralwasser", "thunfisch", "raeucherlachs", "iglo-fischstaebchen"],
    },
  ],
};

/** Wochenersparnis für die Hero-Card auf dem Startscreen. */
export const WEEKLY_SAVINGS = {
  amount: 23.47,
  combinationLabel: "Lidl + REWE",
  itemCount: 18,
  marketCount: 2,
  distanceKm: 7.8,
};

/* ---------------------------------------------------------------
 * Regionsverfügbarkeit
 * Datenmodell entspricht dem späteren Backend-Endpunkt
 * GET /regions/status?lat&lng | ?postalCode
 * ------------------------------------------------------------- */

export type RegionStatus = "available" | "partial" | "unavailable";

export type Region = {
  regionName: string;
  postalCode: string;
  status: RegionStatus;
  activeMarkets: number;
  totalMarkets: number;
  /** ISO-Datum der letzten Datenaktualisierung */
  lastUpdated: string;
  availableRetailers: Chain[];
  plannedRetailers?: Chain[];
  coveragePercentage: number;
  lat: number;
  lng: number;
  /** Echte Anzahl aktueller Angebote, falls vom Backend geliefert. */
  currentOffers?: number;
};

export const CURRENT_REGION: Region = {
  regionName: "Puderbach / Dierdorf",
  postalCode: "56305",
  status: "available",
  activeMarkets: 5,
  totalMarkets: 5,
  lastUpdated: new Date().toISOString(),
  availableRetailers: ["REWE", "Lidl", "ALDI SÜD", "Netto", "EDEKA"],
  coveragePercentage: 100,
  lat: DEFAULT_LOCATION.lat,
  lng: DEFAULT_LOCATION.lng,
  currentOffers: OFFERS.length,
};

/** Weitere Regionen für die Regionsseite (Suche nach Ort/PLZ). */
export const REGIONS: Region[] = [
  CURRENT_REGION,
  {
    regionName: "Neuwied",
    postalCode: "56564",
    status: "partial",
    activeMarkets: 3,
    totalMarkets: 5,
    lastUpdated: new Date(Date.now() - 2 * 864e5).toISOString(),
    availableRetailers: ["REWE", "Lidl", "Netto"],
    plannedRetailers: ["ALDI SÜD", "EDEKA"],
    coveragePercentage: 60,
    lat: 50.4287,
    lng: 7.4606,
  },
  {
    regionName: "Koblenz",
    postalCode: "56068",
    status: "partial",
    activeMarkets: 4,
    totalMarkets: 6,
    lastUpdated: new Date(Date.now() - 4 * 864e5).toISOString(),
    availableRetailers: ["REWE", "Lidl", "ALDI SÜD", "EDEKA"],
    plannedRetailers: ["Netto"],
    coveragePercentage: 67,
    lat: 50.3569,
    lng: 7.5889,
  },
  {
    regionName: "Altenkirchen",
    postalCode: "57610",
    status: "unavailable",
    activeMarkets: 0,
    totalMarkets: 4,
    lastUpdated: new Date(Date.now() - 9 * 864e5).toISOString(),
    availableRetailers: [],
    coveragePercentage: 0,
    lat: 50.6869,
    lng: 7.6462,
  },
  {
    regionName: "Montabaur",
    postalCode: "56410",
    status: "unavailable",
    activeMarkets: 0,
    totalMarkets: 5,
    lastUpdated: new Date(Date.now() - 12 * 864e5).toISOString(),
    availableRetailers: [],
    coveragePercentage: 0,
    lat: 50.4372,
    lng: 7.8253,
  },
];

/** Nächste geplante Regionen – Anzeige ohne erfundene Launch-Daten. */
export const PLANNED_REGIONS = ["Altenkirchen", "Montabaur", "Westerburg", "Linz am Rhein"];

export const RETAILER_OPTIONS: string[] = [
  "REWE",
  "Lidl",
  "ALDI SÜD",
  "ALDI Nord",
  "Netto",
  "EDEKA",
  "Penny",
];

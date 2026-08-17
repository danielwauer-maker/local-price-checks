import {
  type Market,
  type Product,
  effectivePrice,
  getMarket,
  getPrice,
  getProduct,
} from "@/data/demo";

export type BasketEntry = { productId: string; qty: number };

export type PlanLine = {
  product: Product;
  qty: number;
  unitPrice: number;
  isOffer: boolean;
  lineTotal: number;
  /** Ersparnis gegenüber dem teuersten Markt im Vergleich */
  saved: number;
};

export type PlanStop = {
  market: Market;
  lines: PlanLine[];
  total: number;
};

export type ShoppingPlan = {
  stops: PlanStop[];
  total: number;
  /** Bester Preis, wenn alles in einem einzigen Markt gekauft wird */
  singleMarketTotal: number;
  singleMarket: Market | null;
  /** Teuerster Ein-Markt-Einkauf (Referenz für "gespart") */
  worstTotal: number;
  savingsVsSingle: number;
  savingsVsWorst: number;
};

function marketTotal(basket: BasketEntry[], marketId: string): number | null {
  let sum = 0;
  for (const entry of basket) {
    const price = getPrice(entry.productId, marketId);
    if (!price) return null;
    sum += effectivePrice(price) * entry.qty;
  }
  return Math.round(sum * 100) / 100;
}

/**
 * Baut die optimale Einkaufsliste: greedy Auswahl von maximal `maxStops` Märkten,
 * danach wird jedes Produkt dem günstigsten gewählten Markt zugeordnet.
 */
export function buildPlan(
  basket: BasketEntry[],
  marketIds: string[],
  maxStops: number,
): ShoppingPlan {
  const empty: ShoppingPlan = {
    stops: [],
    total: 0,
    singleMarketTotal: 0,
    singleMarket: null,
    worstTotal: 0,
    savingsVsSingle: 0,
    savingsVsWorst: 0,
  };
  if (basket.length === 0 || marketIds.length === 0) return empty;

  const totals = marketIds
    .map((id) => ({ id, total: marketTotal(basket, id) }))
    .filter((t): t is { id: string; total: number } => t.total !== null)
    .sort((a, b) => a.total - b.total);
  if (totals.length === 0) return empty;

  const singleMarketTotal = totals[0]!.total;
  const worstTotal = totals[totals.length - 1]!.total;

  // Greedy: starte mit dem besten Einzelmarkt, füge Märkte hinzu solange sie sparen.
  const chosen: string[] = [totals[0]!.id];
  const costWith = (ids: string[]) =>
    basket.reduce((sum, entry) => {
      const best = Math.min(
        ...ids.map((id) => effectivePrice(getPrice(entry.productId, id)!)),
      );
      return sum + best * entry.qty;
    }, 0);

  while (chosen.length < Math.max(1, maxStops)) {
    let bestId: string | null = null;
    let bestCost = costWith(chosen);
    for (const { id } of totals) {
      if (chosen.includes(id)) continue;
      const cost = costWith([...chosen, id]);
      if (cost < bestCost - 0.01) {
        bestCost = cost;
        bestId = id;
      }
    }
    if (!bestId) break;
    chosen.push(bestId);
  }

  const byMarket = new Map<string, PlanLine[]>();
  let total = 0;
  for (const entry of basket) {
    let winner = chosen[0]!;
    let winnerPrice = Infinity;
    for (const id of chosen) {
      const p = effectivePrice(getPrice(entry.productId, id)!);
      if (p < winnerPrice) {
        winnerPrice = p;
        winner = id;
      }
    }
    const highest = Math.max(
      ...marketIds.map((id) => effectivePrice(getPrice(entry.productId, id)!)),
    );
    const price = getPrice(entry.productId, winner)!;
    const line: PlanLine = {
      product: getProduct(entry.productId)!,
      qty: entry.qty,
      unitPrice: winnerPrice,
      isOffer: Boolean(price.offer),
      lineTotal: Math.round(winnerPrice * entry.qty * 100) / 100,
      saved: Math.round((highest - winnerPrice) * entry.qty * 100) / 100,
    };
    total += line.lineTotal;
    byMarket.set(winner, [...(byMarket.get(winner) ?? []), line]);
  }

  const stops: PlanStop[] = [...byMarket.entries()]
    .map(([id, lines]) => ({
      market: getMarket(id)!,
      lines,
      total: Math.round(lines.reduce((s, l) => s + l.lineTotal, 0) * 100) / 100,
    }))
    .sort((a, b) => b.total - a.total);

  const rounded = Math.round(total * 100) / 100;
  return {
    stops,
    total: rounded,
    singleMarketTotal,
    singleMarket: getMarket(totals[0]!.id) ?? null,
    worstTotal,
    savingsVsSingle: Math.round((singleMarketTotal - rounded) * 100) / 100,
    savingsVsWorst: Math.round((worstTotal - rounded) * 100) / 100,
  };
}

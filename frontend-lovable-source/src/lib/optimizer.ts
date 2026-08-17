import {
  type Market,
  type Product,
  PRICES,
  effectivePrice,
  getMarket,
  getProduct,
} from "@/data/demo";

export type BasketEntry = { productId: string; qty: number };

export type PlanLine = {
  product: Product;
  qty: number;
  unitPrice: number;
  isOffer: boolean;
  lineTotal: number;
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
  singleMarketTotal: number;
  singleMarket: Market | null;
  worstTotal: number;
  savingsVsSingle: number;
  savingsVsWorst: number;
};

function getRuntimePrice(productId: string, marketId: string) {
  return PRICES.find((p) => p.productId === productId && p.marketId === marketId);
}

function marketTotal(basket: BasketEntry[], marketId: string): number | null {
  let sum = 0;
  for (const entry of basket) {
    const price = getRuntimePrice(entry.productId, marketId);
    if (!price) return null;
    sum += effectivePrice(price) * entry.qty;
  }
  return Math.round(sum * 100) / 100;
}

export function buildPlan(
  basket: BasketEntry[],
  marketIds: string[],
  maxStops: number,
): ShoppingPlan {
  const empty: ShoppingPlan = {
    stops: [], total: 0, singleMarketTotal: 0, singleMarket: null,
    worstTotal: 0, savingsVsSingle: 0, savingsVsWorst: 0,
  };
  if (basket.length === 0 || marketIds.length === 0) return empty;

  const coveredBasket = basket.filter((entry) =>
    marketIds.some((id) => Boolean(getRuntimePrice(entry.productId, id))),
  );
  if (coveredBasket.length === 0) return empty;

  const completeTotals = marketIds
    .map((id) => ({ id, total: marketTotal(coveredBasket, id) }))
    .filter((t): t is { id: string; total: number } => t.total !== null)
    .sort((a, b) => a.total - b.total);

  const candidateIds = marketIds.filter((id) =>
    coveredBasket.some((entry) => Boolean(getRuntimePrice(entry.productId, id))),
  );
  if (candidateIds.length === 0) return empty;

  const singleMarketTotal = completeTotals[0]?.total ?? 0;
  const worstTotal = completeTotals.at(-1)?.total ?? 0;

  const chosen: string[] = [];
  const uncovered = new Set(coveredBasket.map((e) => e.productId));
  while (chosen.length < Math.max(1, maxStops) && uncovered.size) {
    let bestId: string | null = null;
    let bestCoverage = -1;
    let bestCost = Infinity;
    for (const id of candidateIds) {
      if (chosen.includes(id)) continue;
      const covered = [...uncovered].filter((productId) => getRuntimePrice(productId, id));
      if (!covered.length) continue;
      const cost = covered.reduce((sum, productId) => {
        const entry = coveredBasket.find((e) => e.productId === productId)!;
        return sum + effectivePrice(getRuntimePrice(productId, id)!) * entry.qty;
      }, 0);
      if (covered.length > bestCoverage || (covered.length === bestCoverage && cost < bestCost)) {
        bestCoverage = covered.length;
        bestCost = cost;
        bestId = id;
      }
    }
    if (!bestId) break;
    chosen.push(bestId);
    for (const productId of [...uncovered]) {
      if (getRuntimePrice(productId, bestId)) uncovered.delete(productId);
    }
  }

  const byMarket = new Map<string, PlanLine[]>();
  let total = 0;
  for (const entry of coveredBasket) {
    const options = chosen
      .map((id) => ({ id, price: getRuntimePrice(entry.productId, id) }))
      .filter((x) => x.price);
    if (!options.length) continue;
    const winner = options.reduce((a, b) =>
      effectivePrice(a.price!) <= effectivePrice(b.price!) ? a : b,
    );
    const winnerPrice = effectivePrice(winner.price!);
    const allAvailable = marketIds
      .map((id) => getRuntimePrice(entry.productId, id))
      .filter(Boolean);
    const highest = allAvailable.length
      ? Math.max(...allAvailable.map((p) => effectivePrice(p!)))
      : winnerPrice;
    const line: PlanLine = {
      product: getProduct(entry.productId)!,
      qty: entry.qty,
      unitPrice: winnerPrice,
      isOffer: Boolean(winner.price!.offer),
      lineTotal: Math.round(winnerPrice * entry.qty * 100) / 100,
      saved: Math.round((highest - winnerPrice) * entry.qty * 100) / 100,
    };
    total += line.lineTotal;
    byMarket.set(winner.id, [...(byMarket.get(winner.id) ?? []), line]);
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
    singleMarket: completeTotals[0] ? getMarket(completeTotals[0].id) ?? null : null,
    worstTotal,
    savingsVsSingle: singleMarketTotal ? Math.round((singleMarketTotal - rounded) * 100) / 100 : 0,
    savingsVsWorst: worstTotal ? Math.round((worstTotal - rounded) * 100) / 100 : 0,
  };
}

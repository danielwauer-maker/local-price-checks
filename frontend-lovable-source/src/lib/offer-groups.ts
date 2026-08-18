import type { OfferItem } from "@/data/demo";

export type GroupedOffer = {
  key: string;
  product: OfferItem["product"];
  price: OfferItem["price"];
  discount: number;
  markets: OfferItem["market"][];
};

function groupKey(offer: OfferItem) {
  const price = offer.price as OfferItem["price"] & {
    validFrom?: string;
    validTo?: string;
    unitPrice?: number | null;
    unitPriceUnit?: string | null;
  };
  return [
    offer.product.id,
    offer.product.unit || "",
    price.offer?.price ?? price.price,
    price.unitPrice ?? "",
    price.unitPriceUnit ?? "",
    price.validFrom ?? "",
    price.validTo ?? price.offer?.until ?? "",
  ].join("|");
}

export function groupIdenticalOffers(offers: OfferItem[]): GroupedOffer[] {
  const grouped = new Map<string, GroupedOffer>();
  for (const offer of offers) {
    const key = groupKey(offer);
    const existing = grouped.get(key);
    if (!existing) {
      grouped.set(key, {
        key,
        product: offer.product,
        price: offer.price,
        discount: offer.discount,
        markets: [offer.market],
      });
      continue;
    }
    if (!existing.markets.some((market) => market.id === offer.market.id)) {
      existing.markets.push(offer.market);
    }
  }
  return [...grouped.values()].sort((a, b) => {
    const product = a.product.name.localeCompare(b.product.name, "de");
    if (product !== 0) return product;
    return (a.price.offer?.price ?? a.price.price) - (b.price.offer?.price ?? b.price.price);
  });
}

export function marketSummary(markets: GroupedOffer["markets"]) {
  if (markets.length === 1) return markets[0].name;
  if (markets.length === 2) return `${markets[0].name} · ${markets[1].name}`;
  return `${markets[0].name} + ${markets.length - 1} weitere Märkte`;
}

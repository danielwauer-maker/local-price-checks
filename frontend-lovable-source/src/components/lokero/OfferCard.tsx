import { Link } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import type { OfferView } from "@/services/lokero-api";
import { formatEuro } from "@/lib/format";
import { useStore } from "@/lib/app-store";
import { MarketLogo } from "./MarketLogo";
import { ProductThumb } from "./CategoryIcon";
import { DiscountBadge } from "./DiscountBadge";

/** Kompakte Kachel für den horizontalen Slider auf dem Startscreen. */
export function OfferTile({ offer }: { offer: OfferView }) {
  return (
    <Link
      to="/produkt/$productId"
      params={{ productId: offer.product.id }}
      className="card-surface flex w-[132px] shrink-0 flex-col p-2.5"
    >
      <div className="flex items-start justify-between">
        <MarketLogo chain={offer.market.chain} size="xs" />
        {offer.discount != null && <DiscountBadge value={offer.discount} size="xs" />}
      </div>
      <ProductThumb categoryId={offer.product.category} className="mx-auto my-2" />
      <p className="line-clamp-2 min-h-[30px] text-[11px] font-medium leading-tight text-navy">
        {offer.product.name}
      </p>
      <p className="tabular mt-1.5 text-[15px] font-bold text-navy">{formatEuro(offer.price)}</p>
      {offer.oldPrice != null && (
        <p className="tabular text-[10px] text-muted-foreground line-through">
          {formatEuro(offer.oldPrice)}
        </p>
      )}
    </Link>
  );
}

/** Listenzeile auf dem Angebote-Screen. */
export function OfferRow({ offer }: { offer: OfferView }) {
  const { addToList } = useStore();
  return (
    <article className="card-surface flex gap-3 p-3">
      <Link to="/produkt/$productId" params={{ productId: offer.product.id }} className="shrink-0">
        <ProductThumb categoryId={offer.product.category} />
      </Link>
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <Link
            to="/produkt/$productId"
            params={{ productId: offer.product.id }}
            className="min-w-0"
          >
            <p className="truncate text-[13px] font-semibold text-navy">{offer.product.name}</p>
            <p className="truncate text-[11px] text-muted-foreground">
              {offer.product.detail ?? offer.product.amount}
            </p>
          </Link>
          <MarketLogo chain={offer.market.chain} size="xs" />
        </div>

        <div className="mt-1.5 flex items-end justify-between gap-2">
          <div className="min-w-0">
            {offer.basePrice && (
              <p className="tabular text-[10px] text-muted-foreground">{offer.basePrice}</p>
            )}
            {offer.leafletPage && (
              <p className="text-[10px] text-muted-foreground">Prospekt S. {offer.leafletPage}</p>
            )}
          </div>
          <div className="text-right">
            <div className="flex items-center justify-end gap-1.5">
              <span className="tabular text-[15px] font-bold text-navy">
                {formatEuro(offer.price)}
              </span>
              {offer.discount != null && <DiscountBadge value={offer.discount} size="xs" />}
            </div>
            {offer.oldPrice != null && (
              <p className="tabular text-[10px] text-muted-foreground line-through">
                statt {formatEuro(offer.oldPrice)}
              </p>
            )}
          </div>
        </div>
      </div>
      <button
        type="button"
        aria-label={`${offer.product.name} zur Liste hinzufügen`}
        onClick={() => {
          addToList(offer.product.id);
          toast.success(`${offer.product.name} auf deiner Liste`);
        }}
        className="tap-target grid h-11 w-11 shrink-0 self-center place-items-center rounded-xl bg-primary-soft text-primary transition-transform duration-150 active:scale-95"
      >
        <Plus className="h-4 w-4" strokeWidth={2.4} />
      </button>
    </article>
  );
}

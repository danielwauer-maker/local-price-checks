import { Link } from "@tanstack/react-router";
import { Heart, ShoppingCart } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import type { OfferView } from "@/services/lokero-api";
import { formatEuro } from "@/lib/format";
import { useStore } from "@/lib/app-store";
import { MarketLogo } from "./MarketLogo";
import { ProductThumb } from "./CategoryIcon";
import { DiscountBadge } from "./DiscountBadge";

function ProductImage({ offer, size = "md" }: { offer: OfferView; size?: "sm" | "md" }) {
  const [failed, setFailed] = useState(false);
  const cls = size === "sm" ? "h-12 w-12" : "h-16 w-16";
  if (failed) return <ProductThumb categoryId={offer.product.category} size={size === "sm" ? "sm" : "md"} />;
  return (
    <div className={`${cls} shrink-0 overflow-hidden rounded-xl bg-white p-1`}>
      <img
        src={offer.product.imageUrl || `/api/lokero/product-media/${encodeURIComponent(offer.product.id)}`}
        alt={offer.product.name}
        loading="lazy"
        className="h-full w-full object-contain"
        onError={() => setFailed(true)}
      />
    </div>
  );
}

export function OfferTile({ offer }: { offer: OfferView }) {
  const { toggleFavoriteProduct, isFavoriteProduct } = useStore();
  const favorite = isFavoriteProduct(offer.product.id);
  return (
    <div className="card-surface relative flex min-w-0 flex-col p-2.5">
      <div className="flex items-start justify-between">
        <MarketLogo chain={offer.market.chain} size="xs" />
        <button
          type="button"
          aria-label={favorite ? "Favorit entfernen" : "Zu Favoriten hinzufügen"}
          onClick={() => toggleFavoriteProduct(offer.product.id)}
          className="grid h-8 w-8 place-items-center rounded-full bg-surface/95 text-discount"
        >
          <Heart className="h-4 w-4" fill={favorite ? "currentColor" : "none"} />
        </button>
      </div>
      <Link to="/produkt/$productId" params={{ productId: offer.product.id }} className="flex flex-1 flex-col">
        <div className="mx-auto my-2"><ProductImage offer={offer} size="sm" /></div>
        <p className="line-clamp-2 min-h-[30px] text-[11px] font-medium leading-tight text-navy">
          {offer.product.name}
        </p>
        <div className="mt-auto flex items-end justify-between gap-1">
          <p className="tabular mt-1.5 text-[15px] font-bold text-navy">{formatEuro(offer.price)}</p>
          {offer.discount != null && <DiscountBadge value={offer.discount} size="xs" />}
        </div>
        {offer.oldPrice != null && (
          <p className="tabular text-[10px] text-muted-foreground line-through">{formatEuro(offer.oldPrice)}</p>
        )}
      </Link>
    </div>
  );
}

export function OfferRow({ offer }: { offer: OfferView }) {
  const { addToList, toggleFavoriteProduct, isFavoriteProduct } = useStore();
  const favorite = isFavoriteProduct(offer.product.id);
  return (
    <article className="card-surface flex gap-3 p-3">
      <Link to="/produkt/$productId" params={{ productId: offer.product.id }} className="shrink-0">
        <ProductImage offer={offer} />
      </Link>
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <Link to="/produkt/$productId" params={{ productId: offer.product.id }} className="min-w-0 flex-1">
            <p className="line-clamp-2 text-[13px] font-semibold leading-snug text-navy">{offer.product.name}</p>
            <p className="mt-0.5 line-clamp-1 text-[11px] text-muted-foreground">{offer.product.detail ?? offer.product.amount}</p>
          </Link>
          <div className="flex shrink-0 items-center gap-1">
            <MarketLogo chain={offer.market.chain} size="xs" />
            <button
              type="button"
              aria-label={favorite ? "Favorit entfernen" : "Zu Favoriten hinzufügen"}
              onClick={() => {
                toggleFavoriteProduct(offer.product.id);
                toast.success(favorite ? "Favorit entfernt" : "Zu Favoriten hinzugefügt");
              }}
              className="grid h-9 w-9 place-items-center rounded-xl text-discount"
            >
              <Heart className="h-4.5 w-4.5" fill={favorite ? "currentColor" : "none"} />
            </button>
          </div>
        </div>

        <div className="mt-1.5 flex items-end justify-between gap-2">
          <div className="min-w-0">
            {offer.basePrice && <p className="tabular text-[10px] text-muted-foreground">{offer.basePrice}</p>}
            {offer.leafletPage && <p className="text-[10px] text-muted-foreground">Prospekt S. {offer.leafletPage}</p>}
          </div>
          <div className="text-right">
            <div className="flex items-center justify-end gap-1.5">
              <span className="tabular text-[15px] font-bold text-navy">{formatEuro(offer.price)}</span>
              {offer.discount != null && <DiscountBadge value={offer.discount} size="xs" />}
            </div>
            {offer.oldPrice != null && (
              <p className="tabular text-[10px] text-muted-foreground line-through">statt {formatEuro(offer.oldPrice)}</p>
            )}
          </div>
        </div>
      </div>
      <button
        type="button"
        aria-label={`${offer.product.name} zur Einkaufsliste hinzufügen`}
        onClick={() => {
          addToList(offer.product.id);
          toast.success(`${offer.product.name} auf deiner Liste`);
        }}
        className="tap-target grid h-11 w-11 shrink-0 self-center place-items-center rounded-xl bg-primary-soft text-primary transition-transform duration-150 active:scale-95"
      >
        <ShoppingCart className="h-4 w-4" strokeWidth={2.2} />
      </button>
    </article>
  );
}

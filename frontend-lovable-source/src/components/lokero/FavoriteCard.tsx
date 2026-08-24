import { Link } from "@tanstack/react-router";
import { Bell, ChevronRight, Heart } from "lucide-react";
import type { AlternativeKind, Product } from "@/data/lokero";
import type { Market } from "@/services/lokero-api";
import { formatEuro } from "@/lib/format";
import { cn } from "@/lib/utils";
import { MarketLogo } from "./MarketLogo";
import { ProductThumb } from "./CategoryIcon";

export function FavoriteCard({
  product,
  market,
  price,
  isFavorite,
  onToggleFavorite,
}: {
  product: Product;
  market?: Market | undefined;
  price: number;
  isFavorite: boolean;
  onToggleFavorite: () => void;
}) {
  return (
    <article className="card-surface flex items-center gap-3 p-3">
      <Link to="/produkt/$productId" params={{ productId: product.id }} className="shrink-0">
        <ProductThumb categoryId={product.category} />
      </Link>
      <Link
        to="/produkt/$productId"
        params={{ productId: product.id }}
        className="min-w-0 flex-1"
      >
        <p className="truncate text-[13px] font-semibold text-navy">{product.name}</p>
        <p className="truncate text-[11px] text-muted-foreground">{product.brand}</p>
      </Link>
      <div className="shrink-0 text-right">
        <p className="tabular text-[14px] font-bold text-navy">{formatEuro(price)}</p>
        {market && <MarketLogo chain={market.chain} size="xs" className="mt-1" />}
      </div>
      <button
        type="button"
        onClick={onToggleFavorite}
        aria-pressed={isFavorite}
        aria-label={isFavorite ? "Favorit entfernen" : "Als Favorit merken"}
        className="tap-target grid shrink-0 place-items-center rounded-xl"
      >
        <Heart
          className={cn(
            "h-5 w-5 transition-all duration-150",
            isFavorite ? "fill-discount text-discount" : "text-muted-foreground",
          )}
        />
      </button>
    </article>
  );
}

const KIND_LABEL: Record<AlternativeKind, string> = {
  identisch: "Gleiches Produkt",
  aehnlich: "Ähnliches Produkt",
  eigenmarke: "Eigenmarke",
  marke: "Markenalternative",
};

export function AlternativeCard({
  product,
  price,
  comparePrice,
  kind,
}: {
  product: Product;
  price: number;
  comparePrice?: number | undefined;
  kind: AlternativeKind;
}) {
  return (
    <Link
      to="/produkt/$productId"
      params={{ productId: product.id }}
      className="mx-3 -mt-1 mb-0 flex items-center gap-3 rounded-b-xl border border-t-0 border-border bg-alt px-3 py-2.5"
    >
      <ProductThumb categoryId={product.category} size="sm" className="bg-white" />
      <div className="min-w-0 flex-1">
        <p className="text-[10px] font-medium uppercase tracking-wide text-primary">
          Günstigere Alternative · {KIND_LABEL[kind]}
        </p>
        <p className="truncate text-[12px] font-semibold text-navy">{product.name}</p>
      </div>
      <div className="shrink-0 text-right">
        <p className="tabular text-[13px] font-bold text-primary">{formatEuro(price)}</p>
        {comparePrice != null && (
          <p className="tabular text-[10px] text-muted-foreground line-through">
            statt {formatEuro(comparePrice)}
          </p>
        )}
      </div>
      <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
    </Link>
  );
}

export function PriceAlertCard({
  targetPrice,
  currentPrice,
  active,
  onToggle,
}: {
  targetPrice: number;
  currentPrice?: number | undefined;
  active: boolean;
  onToggle?: () => void;
}) {
  return (
    <div className="mx-3 -mt-1 flex items-center gap-2.5 rounded-b-xl border border-t-0 border-border bg-alert px-3 py-2.5">
      <Bell className="h-4 w-4 shrink-0 text-alert-foreground" />
      <div className="min-w-0 flex-1">
        <p className="text-[12px] font-semibold text-alert-foreground">
          Preisalarm {active ? "aktiv" : "pausiert"}
        </p>
        <p className="tabular text-[11px] text-alert-foreground/80">
          Zielpreis ≤ {formatEuro(targetPrice)}
          {currentPrice != null && ` · aktuell ${formatEuro(currentPrice)}`}
        </p>
      </div>
      {onToggle && (
        <button
          type="button"
          onClick={onToggle}
          aria-pressed={active}
          className="shrink-0 rounded-lg bg-white/70 px-2.5 py-1.5 text-[11px] font-semibold text-alert-foreground"
        >
          {active ? "Pausieren" : "Aktivieren"}
        </button>
      )}
    </div>
  );
}

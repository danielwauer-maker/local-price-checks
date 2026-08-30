import { Heart } from "lucide-react";
import type { Market } from "@/data/lokero";
import { formatKm } from "@/lib/format";
import { cn } from "@/lib/utils";
import { MarketLogo } from "./MarketLogo";

export function MarketCard({
  market,
  rank,
  isFavorite,
  onToggleFavorite,
  onSelect,
}: {
  market: Market;
  rank?: number;
  isFavorite?: boolean;
  onToggleFavorite?: () => void;
  onSelect?: () => void;
}) {
  return (
    <article className="card-surface flex items-center gap-3 p-3">
      {rank != null && (
        <span className="tabular grid h-6 w-6 shrink-0 place-items-center rounded-full bg-muted-surface text-[11px] font-semibold text-muted-foreground">
          {rank}
        </span>
      )}
      <button
        type="button"
        onClick={onSelect}
        className="flex min-w-0 flex-1 items-center gap-3 text-left"
      >
        <MarketLogo chain={market.chain} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-semibold text-navy">
            {market.chain}{market.city ? ` · ${market.city}` : ""}
          </span>
          <span className="mt-0.5 block truncate text-[11px] font-medium text-navy/80">{market.name}</span>
          <span className="tabular mt-0.5 block truncate text-[11px] text-muted-foreground">
            {formatKm(market.distanceKm)}{market.street ? ` · ${market.street}` : ""}
          </span>
        </span>
      </button>
      {onToggleFavorite && (
        <button
          type="button"
          onClick={onToggleFavorite}
          aria-pressed={isFavorite}
          aria-label={isFavorite ? "Markt aus Favoriten entfernen" : "Markt zu Favoriten"}
          className="tap-target grid shrink-0 place-items-center rounded-xl text-muted-foreground"
        >
          <Heart
            className={cn("h-4.5 w-4.5 transition-colors duration-150", isFavorite && "fill-discount text-discount")}
          />
        </button>
      )}
    </article>
  );
}

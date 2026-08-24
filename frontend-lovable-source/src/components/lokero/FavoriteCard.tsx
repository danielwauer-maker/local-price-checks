import { Link } from "@tanstack/react-router";
import { Bell, ChevronRight, Heart } from "lucide-react";
import type { AlternativeKind, Product } from "@/data/lokero";
import { formatEuro } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ProductImage } from "./ProductImage";

export function FavoriteCard({ product, isFavorite, onToggleFavorite, allowAlternatives = false, onToggleAlternatives }: { product: Product; isFavorite: boolean; onToggleFavorite: () => void; allowAlternatives?: boolean; onToggleAlternatives?: (value: boolean) => void }) {
  return (
    <article className="card-surface p-3">
      <div className="flex items-center gap-3">
        <Link to="/produkt/$productId" params={{ productId: product.id }} className="shrink-0"><ProductImage product={product} /></Link>
        <Link to="/produkt/$productId" params={{ productId: product.id }} className="min-w-0 flex-1"><p className="line-clamp-2 text-[13px] font-semibold text-navy">{product.name}</p></Link>
        <button type="button" onClick={onToggleFavorite} aria-pressed={isFavorite} aria-label={isFavorite ? "Favorit entfernen" : "Als Favorit merken"} className="tap-target grid shrink-0 place-items-center rounded-xl text-discount">
          <Heart className={cn("h-5 w-5 transition-all duration-150 text-discount", isFavorite && "fill-discount")} />
        </button>
      </div>
      {onToggleAlternatives && (
        <div className="mt-3 flex items-center justify-between gap-3 border-t border-border pt-3">
          <span className="text-[12px] font-medium text-navy">Alternativen zulassen</span>
          <button type="button" role="switch" aria-checked={allowAlternatives} onClick={() => onToggleAlternatives(!allowAlternatives)} className={cn("relative h-6 w-11 shrink-0 overflow-hidden rounded-full border-0 p-0 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40", allowAlternatives ? "bg-primary" : "bg-muted-surface")}>
            <span className={cn("absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow-sm transition-transform", allowAlternatives ? "translate-x-5" : "translate-x-0")} />
          </button>
        </div>
      )}
    </article>
  );
}

const KIND_LABEL: Record<AlternativeKind, string> = { identisch: "Gleiches Produkt", aehnlich: "Ähnliches Produkt", eigenmarke: "Eigenmarke", marke: "Markenalternative" };

export function AlternativeCard({ product, price, comparePrice, kind, reason }: { product: Product; price?: number; comparePrice?: number; kind: AlternativeKind; reason?: string }) {
  return (
    <Link to="/produkt/$productId" params={{ productId: product.id }} className="mx-3 -mt-1 mb-0 flex items-center gap-3 rounded-b-xl border border-t-0 border-border bg-alt px-3 py-2.5">
      <ProductImage product={product} size="sm" />
      <div className="min-w-0 flex-1"><p className="text-[10px] font-medium uppercase tracking-wide text-primary">Alternative · {KIND_LABEL[kind]}</p><p className="truncate text-[12px] font-semibold text-navy">{product.name}</p>{reason && <p className="truncate text-[10px] text-muted-foreground">{reason}</p>}</div>
      {price != null && <div className="shrink-0 text-right"><p className="tabular text-[13px] font-bold text-primary">{formatEuro(price)}</p>{comparePrice != null && comparePrice > price && <p className="tabular text-[10px] text-muted-foreground line-through">statt {formatEuro(comparePrice)}</p>}</div>}
      <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
    </Link>
  );
}

export function PriceAlertCard({ targetPrice, currentPrice, active, onToggle }: { targetPrice: number; currentPrice?: number; active: boolean; onToggle?: () => void }) {
  return (
    <div className="mx-3 -mt-1 flex items-center gap-2.5 rounded-b-xl border border-t-0 border-border bg-alert px-3 py-2.5">
      <Bell className="h-4 w-4 shrink-0 text-alert-foreground" />
      <div className="min-w-0 flex-1"><p className="text-[12px] font-semibold text-alert-foreground">Preisalarm {active ? "aktiv" : "pausiert"}</p><p className="tabular text-[11px] text-alert-foreground/80">Zielpreis ≤ {formatEuro(targetPrice)}{currentPrice != null && ` · aktuell ${formatEuro(currentPrice)}`}</p></div>
      {onToggle && <button type="button" onClick={onToggle} aria-pressed={active} className="shrink-0 rounded-lg bg-white/70 px-2.5 py-1.5 text-[11px] font-semibold text-alert-foreground">{active ? "Pausieren" : "Aktivieren"}</button>}
    </div>
  );
}

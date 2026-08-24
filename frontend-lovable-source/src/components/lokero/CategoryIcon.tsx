import {
  Apple,
  Beef,
  Candy,
  Coffee,
  CookingPot,
  CroissantIcon,
  CupSoda,
  Fish,
  Home,
  Milk,
  Package,
  Snowflake,
  Sparkles,
  Wheat,
  type LucideIcon,
} from "lucide-react";
import type { CategoryId } from "@/data/lokero";
import { getCategory } from "@/services/lokero-api";
import { cn } from "@/lib/utils";

const ICONS: Record<string, LucideIcon> = {
  apple: Apple,
  beef: Beef,
  fish: Fish,
  cheese: Package,
  milk: Milk,
  bread: CroissantIcon,
  drink: CupSoda,
  candy: Candy,
  snow: Snowflake,
  wheat: Wheat,
  coffee: Coffee,
  soup: CookingPot,
  sparkles: Sparkles,
  home: Home,
};

export function CategoryIcon({
  categoryId,
  className,
}: {
  categoryId: CategoryId;
  className?: string;
}) {
  const key = getCategory(categoryId)?.icon ?? "package";
  const Icon = ICONS[key] ?? Package;
  return <Icon className={cn("h-5 w-5", className)} strokeWidth={1.9} aria-hidden="true" />;
}

/** Produkt-Thumbnail: neutrale Fläche mit Kategorie-Icon (kein Emoji). */
export function ProductThumb({
  categoryId,
  size = "md",
  className,
}: {
  categoryId: CategoryId;
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  const box = size === "sm" ? "h-10 w-10" : size === "lg" ? "h-24 w-24" : "h-14 w-14";
  const icon = size === "sm" ? "h-5 w-5" : size === "lg" ? "h-10 w-10" : "h-6 w-6";
  return (
    <div
      className={cn(
        "flex shrink-0 items-center justify-center rounded-xl bg-muted-surface text-navy/70",
        box,
        className,
      )}
    >
      <CategoryIcon categoryId={categoryId} className={icon} />
    </div>
  );
}

import { cn } from "@/lib/utils";

/**
 * Rabatt wird nie nur über Farbe kommuniziert – der Prozentwert steht
 * immer als Text im Badge und wird für Screenreader ausgeschrieben.
 */
export function DiscountBadge({
  value,
  size = "sm",
  className,
}: {
  value: number;
  size?: "xs" | "sm";
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md bg-discount font-semibold leading-none text-white",
        size === "xs" ? "px-1.5 py-1 text-[10px]" : "px-2 py-1 text-[11px]",
        className,
      )}
    >
      <span aria-hidden="true">−{value} %</span>
      <span className="sr-only">{value} Prozent reduziert</span>
    </span>
  );
}

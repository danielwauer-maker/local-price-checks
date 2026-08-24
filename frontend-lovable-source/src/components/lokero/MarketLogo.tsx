import type { Chain } from "@/data/lokero";
import { cn } from "@/lib/utils";

const STYLE: Record<Chain, { bg: string; fg: string; label: string }> = {
  REWE: { bg: "#D8232A", fg: "#ffffff", label: "REWE" },
  Lidl: { bg: "#0050AA", fg: "#FFF000", label: "Lidl" },
  "ALDI SÜD": { bg: "#00005F", fg: "#FF7300", label: "ALDI" },
  Netto: { bg: "#FFE500", fg: "#D30032", label: "Netto" },
  EDEKA: { bg: "#003C7D", fg: "#FFDD00", label: "EDEKA" },
};

/** Kompakte Markt-Kennzeichnung (Chain-Badge statt geschützter Logodatei). */
export function MarketLogo({
  chain,
  size = "md",
  className,
}: {
  chain: Chain;
  size?: "xs" | "sm" | "md";
  className?: string;
}) {
  const s = STYLE[chain];
  const box = size === "xs" ? "h-5 px-1.5 text-[9px]" : size === "sm" ? "h-6 px-2 text-[10px]" : "h-9 w-9 text-[10px]";
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-lg font-bold leading-none tracking-tight",
        box,
        className,
      )}
      style={{ backgroundColor: s.bg, color: s.fg }}
    >
      {s.label}
    </span>
  );
}

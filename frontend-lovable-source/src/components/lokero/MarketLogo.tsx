import { useState } from "react";
import type { Chain } from "@/data/lokero";
import { cn } from "@/lib/utils";

const STYLE: Record<Chain, { bg: string; fg: string; label: string }> = {
  REWE: { bg: "#D8232A", fg: "#ffffff", label: "REWE" },
  Lidl: { bg: "#0050AA", fg: "#FFF000", label: "Lidl" },
  "ALDI SÜD": { bg: "#00005F", fg: "#FF7300", label: "ALDI" },
  Netto: { bg: "#FFE500", fg: "#D30032", label: "Netto" },
  EDEKA: { bg: "#003C7D", fg: "#FFDD00", label: "EDEKA" },
};

/**
 * Einheitliche Händlerkennzeichnung.
 *
 * Primär wird das im Spareno-Admin unter "Bilder & Logos" hinterlegte
 * retailer_logo verwendet. Falls für eine Kette noch kein Logo hinterlegt ist
 * oder das Asset nicht geladen werden kann, bleibt der bisherige farbige
 * Chain-Badge als robuster Fallback erhalten.
 */
export function MarketLogo({
  chain,
  size = "md",
  className,
}: {
  chain: Chain;
  size?: "xs" | "sm" | "md";
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  const s = STYLE[chain];
  const badgeBox = size === "xs" ? "h-5 px-1.5 text-[9px]" : size === "sm" ? "h-6 px-2 text-[10px]" : "h-9 w-9 text-[10px]";
  const imageBox = size === "xs" ? "h-5 w-9" : size === "sm" ? "h-7 w-11" : "h-10 w-12";

  if (!failed) {
    return (
      <span className={cn("inline-flex shrink-0 items-center justify-center overflow-hidden rounded-lg bg-white", imageBox, className)}>
        <img
          src={`/api/lokero/retailer-logo/${encodeURIComponent(chain)}`}
          alt={`${chain} Logo`}
          loading="lazy"
          decoding="async"
          width={size === "xs" ? 36 : size === "sm" ? 44 : 48}
          height={size === "xs" ? 20 : size === "sm" ? 28 : 40}
          className="h-full w-full object-contain p-0.5"
          onError={() => setFailed(true)}
        />
      </span>
    );
  }

  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-lg font-bold leading-none tracking-tight",
        badgeBox,
        className,
      )}
      style={{ backgroundColor: s.bg, color: s.fg }}
    >
      {s.label}
    </span>
  );
}

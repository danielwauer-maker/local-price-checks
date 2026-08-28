import { Link } from "@tanstack/react-router";
import { ArrowRight, Info, Trophy } from "lucide-react";
import { formatEuro } from "@/lib/format";

export function SavingsHero({
  amount,
  combinationLabel,
  itemCount,
  marketCount,
  distanceKm,
  explanation,
}: {
  amount: number;
  combinationLabel: string;
  itemCount: number;
  marketCount: number;
  distanceKm: number;
  explanation: string;
}) {
  return (
    <section className="gradient-savings rounded-2xl p-4 text-white shadow-raised">
      <p className="text-center text-[13px] font-medium text-white/85">Diese Woche kannst du</p>
      <p className="tabular mt-0.5 text-center text-[34px] font-bold leading-none">
        {formatEuro(amount)}
      </p>
      <p className="mt-1 text-center text-[15px] font-semibold text-white/95">sparen</p>
      <p className="mt-1 flex items-center justify-center gap-1 text-center text-[11px] text-white/75">
        mit deiner aktuellen Einkaufsliste
        <span role="img" title={explanation} aria-label={explanation}>
          <Info aria-hidden="true" className="h-3 w-3" />
        </span>
      </p>

      <div className="mt-3 rounded-xl bg-white/12 px-3 py-2.5 text-center">
        <p className="flex items-center justify-center gap-1.5 text-[13px] font-semibold">
          <Trophy className="h-3.5 w-3.5 text-[#FDE68A]" />
          Beste Kombination: {combinationLabel}
        </p>
        <p className="tabular mt-1 text-[11px] text-white/75">
          {itemCount} Artikel · {marketCount} Märkte · ca.{" "}
          {distanceKm.toLocaleString("de-DE", { maximumFractionDigits: 1 })} km
        </p>
      </div>

      <Link
        to="/liste"
        className="mt-3 flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-white text-[15px] font-semibold text-primary-deep transition-transform duration-150 active:scale-[0.99]"
      >
        Einkauf optimieren <ArrowRight className="h-4 w-4" />
      </Link>
    </section>
  );
}

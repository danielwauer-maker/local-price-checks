import { cn } from "@/lib/utils";

const SPARENO_MARK_SRC = "/brand/spareno-icon-512.png?v=20260826-rgba";

export function SparenoMark({ className }: { className?: string }) {
  return (
    <img
      src={SPARENO_MARK_SRC}
      alt=""
      aria-hidden="true"
      draggable={false}
      className={cn("h-8 w-8 object-contain", className)}
    />
  );
}

export function SparenoWordmark({
  className,
  markClassName,
}: {
  className?: string;
  markClassName?: string;
}) {
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      <SparenoMark className={cn("h-10 w-10 shrink-0 sm:h-11 sm:w-11", markClassName)} />
      <span
        className="text-[26px] font-bold leading-none tracking-[-0.045em] sm:text-[28px]"
        aria-label="Spareno"
      >
        <span style={{ color: "var(--spareno-navy)" }}>spar</span>
        <span style={{ color: "var(--spareno-green)" }}>eno</span>
      </span>
    </span>
  );
}

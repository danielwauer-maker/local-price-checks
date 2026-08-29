import { cn } from "@/lib/utils";

/**
 * Legacy export names; the rendered brand is Spareno.
 * und dabei ein "L" andeutet. Reines SVG, skaliert verlustfrei.
 */
export function LokeroMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 48 48" fill="none" className={cn("h-8 w-8", className)} aria-hidden="true">
      <path
        d="M39 21c0 10.5-9.4 18.6-13.6 21.7a2.4 2.4 0 0 1-2.8 0C18.4 39.6 9 31.5 9 21a15 15 0 0 1 26.4-9.7"
        stroke="currentColor"
        strokeWidth="5.5"
        strokeLinecap="round"
      />
      <path
        d="M18 21.4l5.6 5.6L41 9.6"
        stroke="currentColor"
        strokeWidth="5.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function LokeroWordmark({
  className,
  markClassName,
}: {
  className?: string;
  markClassName?: string;
}) {
  return (
    <span className={cn("flex items-center gap-1.5", className)}>
      <LokeroMark className={cn("h-6 w-6 text-primary", markClassName)} />
      <span className="text-[19px] font-bold tracking-tight">Spareno</span>
    </span>
  );
}

import { cn } from "@/lib/utils";

export function SparenoMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 64 64"
      fill="none"
      className={cn("h-8 w-8", className)}
      role="img"
      aria-label="Spareno"
    >
      <defs>
        <linearGradient id="spareno-bg" x1="8" y1="4" x2="56" y2="60" gradientUnits="userSpaceOnUse">
          <stop stopColor="#123A7A" />
          <stop offset="1" stopColor="#081E4A" />
        </linearGradient>
        <linearGradient id="spareno-ring" x1="13" y1="11" x2="51" y2="52" gradientUnits="userSpaceOnUse">
          <stop stopColor="#20C9E8" />
          <stop offset="1" stopColor="#22C55E" />
        </linearGradient>
        <linearGradient id="spareno-pin" x1="32" y1="31" x2="32" y2="52" gradientUnits="userSpaceOnUse">
          <stop stopColor="#A7F3D0" />
          <stop offset="1" stopColor="#22C55E" />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="60" height="60" rx="14" fill="url(#spareno-bg)" />
      <g stroke="url(#spareno-ring)" strokeLinecap="round" strokeWidth="2.6">
        <path d="M15 46A24 24 0 0 1 47 14" />
        <path d="M18 18A19 19 0 0 1 49 42" />
        <path d="M21 44A14 14 0 0 1 45 21" />
      </g>
      <circle cx="48.4" cy="18" r="2.7" fill="#22C55E" />
      <path d="M32 52 24.4 41.2c-2.8-4-2.5-9.4.6-13.1 3.8-4.4 10.5-5 15-.9 4.4 3.6 5.2 10.1 2 14.8L32 52Z" fill="url(#spareno-pin)" />
      <circle cx="32" cy="34.6" r="9.1" fill="white" />
      <g stroke="#102A6E" strokeLinecap="round" strokeWidth="2.2">
        <path d="m27.7 39 8.7-8.7" />
        <circle cx="27.6" cy="30.6" r="1.7" />
        <circle cx="36.6" cy="39" r="1.7" />
      </g>
    </svg>
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
    <span className={cn("flex items-center gap-2", className)}>
      <SparenoMark className={cn("h-7 w-7 shrink-0", markClassName)} />
      <span className="text-[19px] font-bold tracking-[-0.03em] leading-none" aria-label="Spareno">
        <span style={{ color: "var(--spareno-navy)" }}>spar</span>
        <span style={{ color: "var(--spareno-green)" }}>eno</span>
      </span>
    </span>
  );
}

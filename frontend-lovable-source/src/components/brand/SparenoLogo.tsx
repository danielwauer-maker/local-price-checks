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
      <g stroke="url(#spareno-ring)" strokeLinecap="round" strokeWidth="3.2">
        <path d="M14 46A25 25 0 0 1 47.5 12.5" />
        <path d="M18 18A19.5 19.5 0 0 1 50 42.5" />
        <path d="M20.5 44.5A14.5 14.5 0 0 1 45.5 20.5" />
      </g>
      <circle cx="48.7" cy="17.7" r="3.1" fill="#22C55E" />
      <path d="M32 53 23.8 41.3c-2.9-4.2-2.6-9.9.7-13.7 4-4.6 11-5.2 15.7-.9 4.6 3.8 5.4 10.6 2.1 15.4L32 53Z" fill="url(#spareno-pin)" />
      <circle cx="32" cy="34.5" r="9.8" fill="white" />
      <g stroke="#102A6E" strokeLinecap="round" strokeWidth="2.5">
        <path d="m27.2 39.3 9.4-9.4" />
        <circle cx="27.3" cy="30.2" r="1.8" />
        <circle cx="36.8" cy="39" r="1.8" />
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

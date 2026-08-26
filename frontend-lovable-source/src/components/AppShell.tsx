import { Link, useRouterState } from "@tanstack/react-router";
import {
  Bell,
  ChevronDown,
  Heart,
  Home,
  ListChecks,
  MapPin,
  SlidersHorizontal,
  Store,
  Tag,
} from "lucide-react";
import type { ReactNode } from "react";
import { useStore } from "@/lib/app-store";
import { cn } from "@/lib/utils";
import { SparenoWordmark } from "@/components/brand/SparenoLogo";

const NAV = [
  { to: "/", label: "Start", icon: Home },
  { to: "/maerkte", label: "Märkte", icon: Store },
  { to: "/favoriten", label: "Favoriten", icon: Heart },
  { to: "/liste", label: "Liste", icon: ListChecks },
  { to: "/angebote", label: "Angebote", icon: Tag },
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="app-frame flex flex-col">
      <div className="flex-1 pb-[92px]">{children}</div>
      <BottomNavigation />
    </div>
  );
}

export function BottomNavigation() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  return (
    <nav
      aria-label="Hauptnavigation"
      className="fixed inset-x-0 bottom-0 z-40 mx-auto w-full max-w-[430px] border-t border-border bg-surface/97 px-1 pb-[max(0.375rem,env(safe-area-inset-bottom))] pt-1.5 backdrop-blur"
    >
      <ul className="flex items-stretch">
        {NAV.map(({ to, label, icon: Icon }) => {
          const active = to === "/" ? pathname === "/" : pathname.startsWith(to);
          return (
            <li key={to} className="flex-1">
              <Link
                to={to}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "tap-target flex flex-col items-center justify-center gap-1 rounded-xl py-1.5 text-[10px] font-medium transition-colors duration-150",
                  active ? "text-primary" : "text-muted-foreground",
                )}
              >
                <Icon className="h-[21px] w-[21px]" strokeWidth={active ? 2.3 : 1.8} />
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/** Kopfbereich des Startscreens mit Branding, Standort und Radius. */
export function TopBar() {
  const { location, radius, setRadius, listCount } = useStore();

  return (
    <header className="bg-surface px-4 pb-3 pt-[max(0.875rem,env(safe-area-inset-top))]">
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3">
        <SparenoWordmark className="min-w-0" />
        <div className="flex shrink-0 items-center">
          <Link
            to="/liste"
            aria-label={`Benachrichtigungen, ${listCount} Artikel auf der Liste`}
            className="tap-target relative grid place-items-center rounded-xl text-navy"
          >
            <Bell className="h-5 w-5" strokeWidth={1.9} />
            {listCount > 0 && (
              <span className="tabular absolute right-1.5 top-1 grid h-4 min-w-4 place-items-center rounded-full bg-discount px-1 text-[9px] font-bold text-white">
                {listCount}
              </span>
            )}
          </Link>
          <Link
            to="/einstellungen"
            aria-label="Einstellungen"
            className="tap-target grid place-items-center rounded-xl text-navy"
          >
            <SlidersHorizontal className="h-5 w-5" strokeWidth={1.9} />
          </Link>
        </div>
      </div>

      <div className="mt-1.5 grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3">
        <Link
          to="/regionen"
          aria-label={`Standort ${location.label} ändern`}
          className="flex min-w-0 items-center gap-1 text-[12px] font-medium text-muted-foreground"
        >
          <MapPin className="h-3.5 w-3.5 shrink-0 text-primary" />
          <span className="truncate">{location.label}</span>
          <ChevronDown className="h-3.5 w-3.5 shrink-0" />
        </Link>
        <label className="flex shrink-0 items-center gap-1 rounded-full bg-muted-surface px-2.5 py-1 text-[12px] font-medium text-navy">
          <span className="sr-only">Suchradius</span>
          <select
            value={radius}
            onChange={(e) => setRadius(Number(e.target.value))}
            className="bg-transparent pr-0.5 text-[12px] font-medium outline-none"
          >
            {[5, 10, 15, 20, 25].map((r) => (
              <option key={r} value={r}>
                {r} km
              </option>
            ))}
          </select>
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
        </label>
      </div>
    </header>
  );
}

export function PageHeader({
  title,
  action,
  subtitle,
}: {
  title: string;
  action?: ReactNode;
  subtitle?: string;
}) {
  return (
    <header className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 bg-surface px-4 pb-3 pt-[max(1rem,env(safe-area-inset-top))]">
      <div className="min-w-0">
        <h1 className="truncate text-[22px] font-bold text-navy">{title}</h1>
        {subtitle && <p className="truncate text-[12px] text-muted-foreground">{subtitle}</p>}
      </div>
      {action}
    </header>
  );
}

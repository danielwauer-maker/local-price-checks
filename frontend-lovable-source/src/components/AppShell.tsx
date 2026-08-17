import { Link, useRouterState } from "@tanstack/react-router";
import { Heart, Home, ListChecks, Map, ScanLine, Tag } from "lucide-react";
import type { ReactNode } from "react";
import { useStore } from "@/lib/app-store";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/", label: "Start", icon: Home },
  { to: "/maerkte", label: "Märkte", icon: Map },
  { to: "/favoriten", label: "Favoriten", icon: Heart },
  { to: "/liste", label: "Liste", icon: ListChecks },
  { to: "/angebote", label: "Angebote", icon: Tag },
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const { basketCount } = useStore();

  return (
    <div className="app-frame flex flex-col">
      {pathname !== "/scanner" && (
        <div className="pointer-events-none fixed inset-x-0 top-0 z-50 mx-auto w-full max-w-[460px] px-4 pt-[max(.75rem,env(safe-area-inset-top))]">
          <div className="flex justify-end">
            <Link
              to="/scanner"
              className="pointer-events-auto flex h-9 w-9 items-center justify-center rounded-full border border-border/70 bg-surface/90 text-primary shadow-card backdrop-blur"
              aria-label="Scanner öffnen"
            >
              <ScanLine className="h-4.5 w-4.5" strokeWidth={2.1} />
            </Link>
          </div>
        </div>
      )}

      <div className="flex-1 pb-24">{children}</div>

      <nav className="fixed inset-x-0 bottom-0 z-40 mx-auto w-full max-w-[460px] border-t border-border bg-surface/95 px-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] pt-2 backdrop-blur">
        <ul className="flex items-end justify-between">
          {NAV.map(({ to, label, icon: Icon }) => {
            const active = to === "/" ? pathname === "/" : pathname.startsWith(to);
            return (
              <li key={to} className="flex-1">
                <Link
                  to={to}
                  className={cn(
                    "relative flex flex-col items-center gap-1 rounded-xl py-1.5 text-[11px] font-medium transition-colors",
                    active ? "text-primary" : "text-muted-foreground",
                  )}
                >
                  <Icon className="h-5 w-5" strokeWidth={active ? 2.4 : 1.8} />
                  {label}
                  {to === "/liste" && basketCount > 0 && (
                    <span className="absolute -top-0.5 right-3 flex h-4 min-w-4 items-center justify-center rounded-full bg-deal px-1 text-[10px] font-bold text-deal-foreground">
                      {basketCount}
                    </span>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <header className="flex items-start justify-between gap-3 px-5 pb-3 pt-[max(1.25rem,env(safe-area-inset-top))]">
      <div>
        <h1 className="text-2xl font-semibold">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      {action}
    </header>
  );
}

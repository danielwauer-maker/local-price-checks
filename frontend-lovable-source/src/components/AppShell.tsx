import { Link, useRouterState } from "@tanstack/react-router";
import { Home, Map, ScanLine, ListChecks, Tag } from "lucide-react";
import type { ReactNode } from "react";
import { useStore } from "@/lib/app-store";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/", label: "Start", icon: Home },
  { to: "/maerkte", label: "Märkte", icon: Map },
  { to: "/scanner", label: "Scan", icon: ScanLine, center: true },
  { to: "/liste", label: "Liste", icon: ListChecks },
  { to: "/angebote", label: "Angebote", icon: Tag },
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const { basketCount } = useStore();

  return (
    <div className="app-frame flex flex-col">
      <div className="flex-1 pb-28">{children}</div>

      <nav className="fixed inset-x-0 bottom-0 z-40 mx-auto w-full max-w-[460px] border-t border-border bg-surface/95 px-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] pt-2 backdrop-blur">
        <ul className="flex items-end justify-between">
          {NAV.map(({ to, label, icon: Icon, ...rest }) => {
            const active = to === "/" ? pathname === "/" : pathname.startsWith(to);
            const center = "center" in rest && rest.center;
            if (center) {
              return (
                <li key={to} className="flex-1">
                  <Link
                    to={to}
                    className="mx-auto -mt-7 flex h-14 w-14 flex-col items-center justify-center rounded-full gradient-hero text-primary-foreground shadow-float"
                    aria-label={label}
                  >
                    <Icon className="h-6 w-6" strokeWidth={2.2} />
                  </Link>
                </li>
              );
            }
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

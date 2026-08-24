import { RefreshCw, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: LucideIcon;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="card-surface flex flex-col items-center px-6 py-10 text-center">
      <span className="flex h-12 w-12 items-center justify-center rounded-full bg-primary-soft text-primary">
        <Icon className="h-6 w-6" strokeWidth={1.8} />
      </span>
      <p className="mt-4 text-[15px] font-semibold">{title}</p>
      {description && (
        <p className="mt-1 max-w-[260px] text-[13px] leading-relaxed text-muted-foreground">
          {description}
        </p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="card-surface px-6 py-8 text-center">
      <p className="text-[15px] font-semibold">Daten konnten nicht geladen werden</p>
      <p className="mt-1 text-[13px] text-muted-foreground">
        Bitte prüfe deine Verbindung und versuche es erneut.
      </p>
      <button
        onClick={onRetry}
        className="mx-auto mt-4 inline-flex h-11 items-center gap-2 rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground"
      >
        <RefreshCw className="h-4 w-4" /> Erneut versuchen
      </button>
    </div>
  );
}

export function SkeletonCard({ className }: { className?: string }) {
  return (
    <div className={cn("card-surface flex gap-3 p-3", className)}>
      <div className="h-14 w-14 shrink-0 animate-pulse rounded-xl bg-muted-surface" />
      <div className="flex-1 space-y-2 py-1">
        <div className="h-3 w-2/3 animate-pulse rounded bg-muted-surface" />
        <div className="h-3 w-1/3 animate-pulse rounded bg-muted-surface" />
        <div className="h-3 w-1/4 animate-pulse rounded bg-muted-surface" />
      </div>
    </div>
  );
}

export function SkeletonList({ count = 4 }: { count?: number }) {
  return (
    <div className="space-y-2.5">
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonCard key={i} />
      ))}
    </div>
  );
}

import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

export type ChipOption = { id: string; label: string; dropdown?: boolean };

export function FilterChips({
  options,
  value,
  onChange,
  className,
}: {
  options: ChipOption[];
  value: string;
  onChange: (id: string) => void;
  className?: string;
}) {
  return (
    <div className={cn("no-scrollbar flex gap-2 overflow-x-auto", className)}>
      {options.map((o) => {
        const active = o.id === value;
        return (
          <button
            key={o.id}
            type="button"
            onClick={() => onChange(o.id)}
            aria-pressed={active}
            className={cn(
              "flex h-9 shrink-0 items-center gap-1 rounded-full border px-3.5 text-[13px] font-medium transition-colors duration-150",
              active
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-surface text-muted-foreground hover:bg-muted-surface",
            )}
          >
            {o.label}
            {o.dropdown && <ChevronDown className="h-3.5 w-3.5" />}
          </button>
        );
      })}
    </div>
  );
}

export function Tabs({
  options,
  value,
  onChange,
}: {
  options: Array<{ id: string; label: string }>;
  value: string;
  onChange: (id: string) => void;
}) {
  return (
    <div role="tablist" className="flex border-b border-border">
      {options.map((o) => {
        const active = o.id === value;
        return (
          <button
            key={o.id}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(o.id)}
            className={cn(
              "relative flex-1 pb-2.5 pt-1 text-[13px] font-semibold transition-colors duration-150",
              active ? "text-primary" : "text-muted-foreground",
            )}
          >
            {o.label}
            <span
              className={cn(
                "absolute inset-x-3 -bottom-px h-0.5 rounded-full transition-opacity duration-150",
                active ? "bg-primary opacity-100" : "opacity-0",
              )}
            />
          </button>
        );
      })}
    </div>
  );
}

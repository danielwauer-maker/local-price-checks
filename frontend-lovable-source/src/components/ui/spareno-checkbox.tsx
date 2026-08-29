import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

export function SparenoCheckbox({
  checked,
  onChange,
  label,
  disabled = false,
  className,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "tap-target grid h-11 w-11 shrink-0 place-items-center rounded-xl focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-45",
        className,
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "grid h-6 w-6 place-items-center rounded-full border-2 transition-colors",
          checked
            ? "border-primary bg-primary text-primary-foreground"
            : "border-border bg-surface text-transparent",
        )}
      >
        <Check className="h-3.5 w-3.5" strokeWidth={3} />
      </span>
    </button>
  );
}


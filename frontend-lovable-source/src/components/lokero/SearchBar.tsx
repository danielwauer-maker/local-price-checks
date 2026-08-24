import { useNavigate } from "@tanstack/react-router";
import { ScanLine, Search } from "lucide-react";
import { useState } from "react";

export function SearchBar({
  defaultValue = "",
  autoFocus = false,
  onChange,
  placeholder = "Produkte, Märkte oder Angebote suchen …",
}: {
  defaultValue?: string;
  autoFocus?: boolean;
  onChange?: (value: string) => void;
  placeholder?: string;
}) {
  const navigate = useNavigate();
  const [value, setValue] = useState(defaultValue);

  return (
    <form
      role="search"
      onSubmit={(e) => {
        e.preventDefault();
        if (!onChange) navigate({ to: "/suche", search: { q: value } });
      }}
      className="flex h-12 items-center gap-2 rounded-xl border border-border bg-surface px-3.5"
    >
      <Search className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      <input
        value={value}
        autoFocus={autoFocus}
        onChange={(e) => {
          setValue(e.target.value);
          onChange?.(e.target.value);
        }}
        onFocus={() => {
          if (!onChange) navigate({ to: "/suche", search: { q: value } });
        }}
        aria-label="Suche"
        placeholder={placeholder}
        className="min-w-0 flex-1 bg-transparent text-[13px] outline-none placeholder:text-muted-foreground"
      />
      <button
        type="button"
        onClick={() => navigate({ to: "/scanner" })}
        aria-label="Barcode scannen"
        className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-muted-foreground hover:bg-muted-surface"
      >
        <ScanLine className="h-4 w-4" />
      </button>
    </form>
  );
}

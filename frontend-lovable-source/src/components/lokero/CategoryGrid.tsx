import { Link } from "@tanstack/react-router";
import { LayoutGrid } from "lucide-react";
import { CategoryIcon } from "./CategoryIcon";
import { CATEGORIES, HOME_CATEGORY_IDS } from "@/data/lokero";

const QUICK_TAGS = [
  { id: "vegan", label: "Vegan" },
  { id: "glutenfrei", label: "Glutenfrei" },
] as const;

export function CategoryGrid() {
  const cats = HOME_CATEGORY_IDS.map((id) => CATEGORIES.find((c) => c.id === id)!);

  return (
    <div className="grid grid-cols-4 gap-2">
      {cats.map((c) => (
        <Link
          key={c.id}
          to="/angebote"
          search={{ category: c.id }}
          className="flex flex-col items-center gap-1.5 rounded-xl border border-border bg-surface px-1 py-3 text-center transition-colors duration-150 active:bg-muted-surface"
        >
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-primary-soft text-primary">
            <CategoryIcon categoryId={c.id} className="h-4.5 w-4.5" />
          </span>
          <span className="text-[10px] font-medium leading-tight text-navy">{c.label}</span>
        </Link>
      ))}
      {QUICK_TAGS.map((t) => (
        <Link
          key={t.id}
          to="/angebote"
          search={{ tag: t.id }}
          className="flex flex-col items-center gap-1.5 rounded-xl border border-border bg-surface px-1 py-3 text-center transition-colors duration-150 active:bg-muted-surface"
        >
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-primary-soft text-primary">
            <CategoryIcon categoryId="obst-gemuese" className="h-4.5 w-4.5" />
          </span>
          <span className="text-[10px] font-medium leading-tight text-navy">{t.label}</span>
        </Link>
      ))}
      <Link
        to="/angebote"
        className="flex flex-col items-center gap-1.5 rounded-xl border border-border bg-surface px-1 py-3 text-center"
      >
        <span className="grid h-8 w-8 place-items-center rounded-lg bg-muted-surface text-navy/70">
          <LayoutGrid className="h-4 w-4" strokeWidth={1.9} />
        </span>
        <span className="text-[10px] font-medium leading-tight text-navy">Mehr</span>
      </Link>
    </div>
  );
}

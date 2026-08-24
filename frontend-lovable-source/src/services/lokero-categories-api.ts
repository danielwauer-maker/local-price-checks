import { CATEGORIES } from "@/data/lokero";

export type RuntimeCategory = {
  id: string;
  label: string;
  icon?: string;
  count?: number;
};

export async function fetchCategories(): Promise<RuntimeCategory[]> {
  try {
    const response = await fetch("/api/lokero/categories", {
      credentials: "include",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error(`categories ${response.status}`);
    const rows = (await response.json()) as RuntimeCategory[];
    return rows.length ? rows : CATEGORIES;
  } catch {
    return CATEGORIES;
  }
}

export function formatEuro(value: number): string {
  return value.toLocaleString("de-DE", { style: "currency", currency: "EUR" });
}

export function formatKm(value: number): string {
  return `${value.toLocaleString("de-DE", { maximumFractionDigits: 1 })} km`;
}

export function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" });
}

function formatDateWithYear(date: Date): string {
  return date.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" });
}

export function formatDateRange(from: string, to: string): string {
  const start = new Date(from);
  const end = new Date(to);

  // /offer-week uses a same-day fallback when there are currently no active offers.
  // For a UI labelled "Diese Woche" that sentinel should still read as the actual
  // calendar week instead of e.g. "28.08. – 28.08.2026".
  if (from === to && !Number.isNaN(start.getTime())) {
    const monday = new Date(start);
    const weekday = monday.getDay();
    const daysSinceMonday = (weekday + 6) % 7;
    monday.setDate(monday.getDate() - daysSinceMonday);

    const sunday = new Date(monday);
    sunday.setDate(monday.getDate() + 6);

    return `${formatDate(monday.toISOString())} – ${formatDateWithYear(sunday)}`;
  }

  return `${formatDate(from)} – ${formatDateWithYear(end)}`;
}

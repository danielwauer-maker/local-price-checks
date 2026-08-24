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

export function formatDateRange(from: string, to: string): string {
  const end = new Date(to);
  return `${formatDate(from)} – ${formatDate(to)}${end.getFullYear()}`;
}


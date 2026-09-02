import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Car, CheckCircle2, ChevronDown, Info, MapPin } from "lucide-react";
import type { OptimizedStop, OptimizedTrip } from "@/data/lokero";
import { getMarket, getProduct } from "@/services/lokero-api";
import { useStore } from "@/lib/app-store";
import { formatEuro } from "@/lib/format";
import { cn } from "@/lib/utils";
import { MarketLogo } from "./MarketLogo";
import { ProductThumb } from "./CategoryIcon";

type RouteDetails = { distanceKm: number; order: string[]; stopNames: string[]; legsKm: number[]; estimated: boolean; source: string };

async function fetchRouteDetails(): Promise<RouteDetails> {
  const response = await fetch("/api/lokero/optimized-route-details", { credentials: "include", headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error("route details unavailable");
  return response.json() as Promise<RouteDetails>;
}

export function OptimizedTripSummary({ trip }: { trip: OptimizedTrip }) {
  const { listEntries, manualListItems } = useStore();
  const coveredItemCount = trip.stops.reduce((sum, stop) => sum + stop.itemCount, 0);
  const visibleItemCount = listEntries.length + manualListItems.length;
  const totalItemCount = visibleItemCount > 0 ? visibleItemCount : trip.itemCount;
  const noSingleStoreComparison = trip.stops.length > 1 && trip.savings <= 0.01;
  const coverageValue = totalItemCount > 0 ? `${coveredItemCount}/${totalItemCount}` : "0";
  const kpis = [
    { value: coverageValue, label: "preislich" },
    { value: formatEuro(trip.total), label: "berechenbar" },
    { value: noSingleStoreComparison ? "–" : formatEuro(trip.savings), label: noSingleStoreComparison ? "Ein-Markt" : "Ersparnis", highlight: !noSingleStoreComparison },
    { value: formatEuro(trip.travelCost), label: "Fahrtkosten" },
  ];
  return <section className="gradient-savings rounded-2xl p-4 text-white shadow-raised"><p className="flex items-center gap-1.5 text-[14px] font-semibold"><CheckCircle2 className="h-4 w-4" /> Dein optimaler Einkauf</p><div className="mt-3 grid grid-cols-4 gap-1.5">{kpis.map((k) => <div key={k.label} className="rounded-xl bg-white/12 px-1 py-2 text-center"><p className={cn("tabular text-[13px] font-bold leading-tight", k.highlight && "text-[#BBF7D0]")}>{k.value}</p><p className="mt-0.5 text-[9px] leading-tight text-white/75">{k.label}</p></div>)}</div><div className="mt-3 rounded-xl bg-white/12 px-3 py-2 text-center">{noSingleStoreComparison ? <><p className="text-[12px] font-semibold">{trip.stops.length} Märkte nötig für alle aktuellen Angebotsartikel</p><p className="mt-0.5 flex items-center justify-center gap-1 text-[10px] text-white/75"><Info className="h-3 w-3" /> Kein einzelner Markt deckt aktuell alle {coveredItemCount} preislich vergleichbaren Artikel ab.</p></> : <><p className="text-[12px] font-semibold">{trip.combinationLabel} spart dir {formatEuro(trip.savings)}</p><p className="mt-0.5 flex items-center justify-center gap-1 text-[10px] text-white/75"><Info className="h-3 w-3" /> {trip.savingsExplanation}</p></>}</div>{coveredItemCount < totalItemCount && <p className="mt-2 text-center text-[10px] text-white/75">{coveredItemCount} von {totalItemCount} Artikeln haben aktuell einen Marktpreis; die übrigen bleiben auf deiner Liste.</p>}</section>;
}

export function TripRouteRow({ trip }: { trip: OptimizedTrip }) {
  const [open, setOpen] = useState(false);
  const details = useQuery({ queryKey: ["optimized-route-details", trip.distanceKm, trip.stops.map((stop) => stop.marketId).join(",")], queryFn: fetchRouteDetails, enabled: open, staleTime: 30_000 });
  const fallbackNames = trip.stops.map((stop) => getMarket(stop.marketId)?.name ?? stop.marketName ?? "Markt");
  const stopNames = details.data?.stopNames?.length ? details.data.stopNames : fallbackNames;
  const route = ["Zuhause", ...stopNames, "Zuhause"];
  const legs = details.data?.legsKm ?? [];
  return <div className="card-surface overflow-hidden text-[12px] text-muted-foreground"><button type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open} className="tabular flex w-full items-center gap-2 px-3 py-2.5 text-left"><Car className="h-4 w-4 shrink-0 text-info" /><span className="min-w-0 flex-1">Fahrtkosten: {formatEuro(trip.travelCost)} · {trip.stops.length} Stopps · {trip.distanceKm.toLocaleString("de-DE", { maximumFractionDigits: 1 })} km</span><ChevronDown className={cn("h-4 w-4 shrink-0 transition-transform", open && "rotate-180")} /></button>{open && <div className="border-t border-border px-3 py-3"><p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Rundtour</p>{details.isLoading && <p className="py-2 text-[10px] text-muted-foreground">Straßenabschnitte werden geladen …</p>}<div className="space-y-2">{route.map((label, index) => <div key={`${label}-${index}`} className="flex items-center gap-2"><span className={cn("grid h-6 w-6 shrink-0 place-items-center rounded-full", index === 0 || index === route.length - 1 ? "bg-info/10 text-info" : "bg-primary-soft text-primary")}>{index === 0 || index === route.length - 1 ? <Car className="h-3.5 w-3.5" /> : <MapPin className="h-3.5 w-3.5" />}</span><span className="min-w-0 flex-1 truncate text-[11px] font-medium text-navy">{label}</span>{index > 0 && legs[index - 1] != null && <span className="tabular text-[10px] font-medium text-muted-foreground">{legs[index - 1].toLocaleString("de-DE", { maximumFractionDigits: 1 })} km</span>}</div>)}</div><p className="mt-2 text-[10px] leading-relaxed text-muted-foreground">Die Kilometer je Abschnitt stammen aus derselben Straßen-Routenmatrix wie die Gesamtrundtour.{details.data?.estimated ? " Routingdienst nicht erreichbar – Werte sind ersatzweise geschätzt." : ""}</p></div>}</div>;
}

export function ShoppingMarketGroup({ stop }: { stop: OptimizedStop }) {
  const [open, setOpen] = useState(false); const market = getMarket(stop.marketId); const preview = stop.productIds.slice(0, 5); const rest = stop.productIds.length - preview.length; if (!market) return null;
  return <article className="card-surface p-3"><div className="flex items-center gap-3"><MarketLogo chain={market.chain} /><div className="min-w-0 flex-1"><p className="truncate text-[13px] font-semibold text-navy">{market.name}</p><p className="text-[11px] text-muted-foreground">{stop.itemCount} Artikel</p></div><p className="tabular text-[14px] font-bold text-navy">{formatEuro(stop.total)}</p></div><div className="mt-3 flex gap-2">{preview.map((id) => { const p = getProduct(id); return p ? <ProductThumb key={id} categoryId={p.category} size="sm" /> : null; })}{rest > 0 && <span className="tabular grid h-10 w-10 place-items-center rounded-xl bg-muted-surface text-[11px] font-semibold text-muted-foreground">+{rest}</span>}</div><button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="mt-2 flex w-full items-center justify-center gap-1 py-1.5 text-[11px] font-medium text-muted-foreground">Details {open ? "ausblenden" : "anzeigen"}<ChevronDown className={cn("h-3.5 w-3.5 transition-transform duration-200", open && "rotate-180")} /></button>{open && <ul className="mt-1 space-y-1.5 border-t border-border pt-2">{stop.productIds.map((id) => { const p = getProduct(id); if (!p) return null; return <li key={id} className="flex items-center gap-2 text-[12px]"><ProductThumb categoryId={p.category} size="sm" className="h-8 w-8" /><span className="min-w-0 flex-1 truncate text-navy">{p.name}</span><span className="text-[11px] text-muted-foreground">{p.amount}</span></li>; })}</ul>}</article>;
}

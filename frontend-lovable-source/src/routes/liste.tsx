import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { Check, ChevronDown, ExternalLink, MapPinned, Minus, Plus, Search, Sparkles, Trash2 } from "lucide-react";
import { PageHeader } from "@/components/AppShell";
import { useActiveMarketIds, useStore } from "@/lib/app-store";
import { PRODUCTS, formatEuro } from "@/data/demo";
import { cn } from "@/lib/utils";

type BackendPlanLine = { product: (typeof PRODUCTS)[number]; qty: number; unitPrice: number; isOffer: boolean; lineTotal: number; saved: number; };
type BackendPlanStop = { market: { id: string; name: string; chain: string; city: string; openUntil: string; lat?: number; lng?: number }; lines: BackendPlanLine[]; total: number; };
type BackendPlan = { stops: BackendPlanStop[]; total: number; merchandiseTotal: number; travelKm: number; travelCost: number; singleMarketTotal: number; singleMarket: { chain: string; name: string } | null; savingsVsSingle: number; offeredItems: number; totalItems: number; missing: Array<{ product: (typeof PRODUCTS)[number]; qty: number }>; };
type RouteDetails = { legs: Array<{ from: string; to: string; km: number }>; googleMapsUrl: string | null; totalKm: number; };

const EMPTY_PLAN: BackendPlan = { stops: [], total: 0, merchandiseTotal: 0, travelKm: 0, travelCost: 0, singleMarketTotal: 0, singleMarket: null, savingsVsSingle: 0, offeredItems: 0, totalItems: 0, missing: [] };

export const Route = createFileRoute("/liste")({
  head: () => ({ meta: [{ title: "Optimale Einkaufsliste & Marktvergleich – LocalPrices" }] }),
  component: ListPage,
});

function ListPage() {
  const { basketEntries, setQty, addToBasket, clearBasket, maxStops, setMaxStops, hydrated, checked, toggleChecked } = useStore();
  const activeIds = useActiveMarketIds();
  const [query, setQuery] = useState("");
  const [plan, setPlan] = useState<BackendPlan>(EMPTY_PLAN);
  const [planLoading, setPlanLoading] = useState(false);
  const [routeOpen, setRouteOpen] = useState(false);
  const [route, setRoute] = useState<RouteDetails | null>(null);

  useEffect(() => {
    if (!hydrated) return;
    let live = true;
    const timer = window.setTimeout(() => {
      setPlanLoading(true);
      fetch(`/api/plan?max_stores=${maxStops}`)
        .then((r) => { if (!r.ok) throw new Error(`plan ${r.status}`); return r.json() as Promise<BackendPlan>; })
        .then((payload) => live && setPlan(payload))
        .catch((error) => console.error("LocalPrices plan failed", error))
        .finally(() => live && setPlanLoading(false));
    }, 200);
    return () => { live = false; window.clearTimeout(timer); };
  }, [hydrated, basketEntries, activeIds, maxStops]);

  useEffect(() => {
    setRoute(null);
    if (!routeOpen) return;
    fetch(`/api/ux/route-plan?max_stores=${maxStops}`).then((r) => r.json()).then(setRoute).catch(() => setRoute({ legs: [], googleMapsUrl: null, totalKm: 0 }));
  }, [routeOpen, maxStops, plan.total]);

  const suggestions = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return PRODUCTS.filter((p) => p.name.toLowerCase().includes(q) || p.brand.toLowerCase().includes(q)).slice(0, 6);
  }, [query]);

  const CheckButton = ({ id }: { id: string }) => {
    const done = checked.includes(id);
    return <button onClick={() => toggleChecked(id)} aria-label={done ? "Als nicht gekauft markieren" : "Als gekauft markieren"} className={cn("flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2", done ? "border-primary bg-primary text-primary-foreground" : "border-border bg-surface")} >{done && <Check className="h-3.5 w-3.5" />}</button>;
  };

  return (
    <div>
      <PageHeader title="Einkaufsliste" subtitle={`${basketEntries.length} Artikel · ${activeIds.length} Märkte im Vergleich`} action={basketEntries.length > 0 ? <button onClick={clearBasket} className="mt-1 flex items-center gap-1 rounded-full bg-secondary px-3 py-1.5 text-xs font-semibold text-secondary-foreground"><Trash2 className="h-3.5 w-3.5" /> leeren</button> : undefined} />

      <div className="px-5">
        <div className="flex items-center gap-2 rounded-2xl bg-surface px-4 py-3 shadow-card"><Search className="h-4 w-4 text-muted-foreground" /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Artikel hinzufügen…" className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground" /></div>
        {suggestions.length > 0 && <ul className="mt-2 overflow-hidden rounded-2xl bg-surface shadow-card">{suggestions.map((p) => <li key={p.id}><button onClick={() => { addToBasket(p.id); setQuery(""); }} className="flex w-full items-center gap-3 border-b border-border px-4 py-2.5 text-left last:border-0"><span className="text-xl">{p.emoji}</span><span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{p.name}</span><span className="block text-xs text-muted-foreground">{p.brand} · {p.unit}</span></span><Plus className="h-4 w-4 text-primary" /></button></li>)}</ul>}
      </div>

      {basketEntries.length === 0 ? <p className="mx-5 mt-6 surface-card p-8 text-center text-sm text-muted-foreground">Deine Liste ist leer. Füge Artikel hinzu oder übernimm Angebote.</p> : <>
        <section className="mx-5 mt-5 overflow-hidden rounded-3xl gradient-hero p-5 text-primary-foreground shadow-float">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide opacity-80"><Sparkles className="h-4 w-4" /> Optimaler Plan</div>
          <p className="tabular mt-2 text-4xl font-bold">{formatEuro(plan.total)}</p>
          <p className="mt-1 text-sm opacity-85">{plan.offeredItems} von {plan.totalItems} Artikeln im Angebot · {plan.stops.length} {plan.stops.length === 1 ? "Markt" : "Märkte"}</p>
          <div className="mt-4 grid grid-cols-2 gap-2 text-sm">
            <div className="rounded-2xl bg-white/12 px-3 py-2"><span className="block text-[11px] opacity-80">Waren</span><span className="tabular font-bold">{formatEuro(plan.merchandiseTotal)}</span></div>
            <button onClick={() => setRouteOpen((x) => !x)} className="rounded-2xl bg-white/12 px-3 py-2 text-left"><span className="flex items-center justify-between text-[11px] opacity-80"><span>Fahrt · {plan.travelKm.toFixed(1)} km</span><ChevronDown className={cn("h-3.5 w-3.5 transition-transform", routeOpen && "rotate-180")} /></span><span className="tabular font-bold">{formatEuro(plan.travelCost)}</span></button>
          </div>
          {routeOpen && <div className="mt-3 rounded-2xl bg-black/10 p-3 text-xs">
            {!route && <p className="opacity-80">Route wird berechnet…</p>}
            {route?.legs.map((leg, i) => <div key={`${leg.from}-${leg.to}-${i}`} className="flex items-start justify-between gap-3 border-b border-white/15 py-2 last:border-0"><span>{i + 1}. {leg.from} → {leg.to}</span><b className="tabular shrink-0">{leg.km.toFixed(1)} km</b></div>)}
            {route?.googleMapsUrl && <a href={route.googleMapsUrl} target="_blank" rel="noreferrer" className="mt-3 flex items-center justify-center gap-2 rounded-xl bg-white px-3 py-2 font-semibold text-primary"><MapPinned className="h-4 w-4" /> Route in Google Maps <ExternalLink className="h-3.5 w-3.5" /></a>}
          </div>}
          {plan.singleMarket && <p className="mt-3 text-xs opacity-85">Gegenüber bestem Einzelmarkt {plan.savingsVsSingle > 0 ? `${formatEuro(plan.savingsVsSingle)} günstiger` : "kein Mehrmarkt-Vorteil"}.</p>}
        </section>

        <div className="mx-5 mt-4 flex items-center justify-between rounded-2xl bg-surface p-3 shadow-card"><span className="text-sm font-medium">Max. Anzahl Märkte</span><div className="flex gap-1">{[1,2,3].map((n) => <button key={n} onClick={() => setMaxStops(n)} className={cn("h-8 w-9 rounded-xl text-sm font-semibold transition-colors", maxStops === n ? "bg-primary text-primary-foreground" : "bg-secondary text-secondary-foreground")}>{n}</button>)}</div></div>
        {planLoading && <p className="px-5 pt-3 text-center text-xs text-muted-foreground">Plan wird aktualisiert…</p>}

        <section className="mt-5 space-y-4 px-5">
          {plan.stops.map((stop, i) => <article key={stop.market.id} className="surface-card overflow-hidden">
            <header className="flex items-center gap-3 border-b border-border px-4 py-3"><span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary text-xs font-bold text-primary-foreground">{i+1}</span><div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold">{stop.market.name}</p><p className="text-[11px] text-muted-foreground">{stop.market.city}</p></div><span className="tabular text-sm font-bold">{formatEuro(stop.total)}</span></header>
            <ul>{stop.lines.map((line) => { const done = checked.includes(line.product.id); return <li key={line.product.id} className={cn("flex items-center gap-3 border-b border-border px-4 py-2.5 last:border-0", done && "bg-secondary/35 opacity-65")}><CheckButton id={line.product.id} /><span className="text-xl">{line.product.emoji}</span><div className="min-w-0 flex-1"><p className={cn("truncate text-sm font-medium", done && "line-through")}>{line.product.name}</p><p className="text-[11px] text-muted-foreground">{line.product.unit}{line.isOffer && <span className="ml-1.5 rounded-full bg-deal/12 px-1.5 py-0.5 font-semibold text-deal">Angebot</span>}</p></div><div className="flex items-center gap-1.5"><button onClick={() => setQty(line.product.id, line.qty-1)} className="flex h-7 w-7 items-center justify-center rounded-full bg-secondary"><Minus className="h-3.5 w-3.5" /></button><span className="tabular w-4 text-center text-sm font-semibold">{line.qty}</span><button onClick={() => setQty(line.product.id, line.qty+1)} className="flex h-7 w-7 items-center justify-center rounded-full bg-secondary"><Plus className="h-3.5 w-3.5" /></button></div><span className="tabular w-14 text-right text-sm font-semibold">{formatEuro(line.lineTotal)}</span></li>; })}</ul>
          </article>)}

          {plan.missing.length > 0 && <article className="surface-card overflow-hidden border border-dashed border-border"><header className="px-4 py-3 text-sm font-semibold">Aktuell ohne Angebot</header><ul>{plan.missing.map((line) => { const done = checked.includes(line.product.id); return <li key={line.product.id} className={cn("flex items-center gap-3 border-t border-border px-4 py-2.5", done && "opacity-55")}><CheckButton id={line.product.id} /><span className={cn("min-w-0 flex-1 truncate text-sm", done && "line-through")}>{line.product.name}</span><span className="text-xs text-muted-foreground">Menge {line.qty}</span></li>; })}</ul></article>}
        </section>
        <p className="px-5 pt-4 text-center text-[11px] text-muted-foreground">Abgehakte Artikel bleiben bis „Liste leeren“ sichtbar und werden beim nächsten Öffnen wiederhergestellt.</p>
      </>}
    </div>
  );
}

import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ChevronLeft, ChevronRight, ExternalLink, Heart, MapPinned, Minus, Plus, RefreshCw, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useStore } from "@/lib/app-store";

export const Route = createFileRoute("/markt/$id")({ component: MarketDetailPage });

type Detail = {
  id: string;
  name: string;
  chain: string;
  address: string;
  lat: number | null;
  lng: number | null;
  currentProspectUrl: string | null;
  futureProspectUrl: string | null;
  directions: { google: string | null; apple: string | null; osm: string | null };
};

type Prospect = {
  id: number;
  period: "current" | "next";
  validFrom: string | null;
  validTo: string | null;
  pageCount: number;
  viewerUrl: string;
  sourceUrl: string;
  fetchedAt: string | null;
};

type ProspectsPayload = { current: Prospect | null; next: Prospect | null };
type ViewerState = { label: string; prospect: Prospect; page: number; zoom: number };

function dateRange(p: Prospect | null) {
  if (!p?.validFrom || !p.validTo) return "";
  const from = new Date(`${p.validFrom}T00:00:00`);
  const to = new Date(`${p.validTo}T00:00:00`);
  return `${from.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" })} – ${to.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" })}`;
}

function MarketDetailPage() {
  const { id } = Route.useParams();
  const { selected, toggleSelected, marketsInRadius } = useStore();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [prospects, setProspects] = useState<ProspectsPayload>({ current: null, next: null });
  const [loadingProspects, setLoadingProspects] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [viewer, setViewer] = useState<ViewerState | null>(null);

  useEffect(() => {
    fetch(`/api/ux/stores/${id}`).then((r) => r.ok ? r.json() : Promise.reject()).then(setDetail).catch(() => setDetail(null));
  }, [id]);

  useEffect(() => {
    setLoadingProspects(true);
    fetch(`/api/prospects/stores/${id}`)
      .then((r) => r.ok ? r.json() : Promise.reject())
      .then((payload: ProspectsPayload) => setProspects(payload))
      .catch(() => setProspects({ current: null, next: null }))
      .finally(() => setLoadingProspects(false));
  }, [id]);

  const market = marketsInRadius.find((m) => m.id === id);
  const chosen = selected.includes(id);
  const viewerSrc = useMemo(() => viewer ? `${viewer.prospect.viewerUrl}#page=${viewer.page}&zoom=${viewer.zoom}` : "", [viewer]);

  async function refreshProspects() {
    setRefreshing(true);
    try {
      await fetch(`/api/prospects/stores/${id}/refresh`, { method: "POST" });
      const response = await fetch(`/api/prospects/stores/${id}`);
      if (response.ok) setProspects(await response.json());
    } finally {
      setRefreshing(false);
    }
  }

  function openViewer(label: string, prospect: Prospect | null) {
    if (!prospect) return;
    setViewer({ label, prospect, page: 1, zoom: 100 });
  }

  if (!detail) return <div className="px-5 pt-8 text-sm text-muted-foreground">Marktdaten werden geladen…</div>;

  return (
    <div>
      <header className="px-5 pb-4 pt-[max(1.25rem,env(safe-area-inset-top))]">
        <Link to="/maerkte" className="mb-4 inline-flex items-center gap-1 text-sm font-medium text-primary"><ArrowLeft className="h-4 w-4" /> Märkte</Link>
        <div className="surface-card overflow-hidden">
          {(market as any)?.imageUrl && <img src={(market as any).imageUrl} alt={detail.name} className="h-36 w-full object-cover" />}
          <div className="flex items-start gap-3 p-4">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-2xl bg-surface-2 text-xs font-bold text-primary">
              {(market as any)?.logoUrl ? <img src={(market as any).logoUrl} alt={detail.chain} className="h-full w-full object-contain p-1" /> : detail.chain.slice(0, 4)}
            </div>
            <div className="min-w-0 flex-1"><h1 className="text-xl font-semibold">{detail.name}</h1><p className="mt-1 text-sm text-muted-foreground">{detail.address}</p></div>
            <button onClick={() => toggleSelected(id)} className={cn("flex h-10 w-10 items-center justify-center rounded-full", chosen ? "bg-deal/12 text-deal" : "bg-secondary text-muted-foreground")} aria-label="Markt auswählen"><Heart className={cn("h-5 w-5", chosen && "fill-current")} /></button>
          </div>
        </div>
      </header>

      <section className="space-y-3 px-5">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">Prospekte</h2>
          <button onClick={refreshProspects} disabled={refreshing} className="inline-flex items-center gap-1 rounded-full bg-secondary px-3 py-1.5 text-xs font-semibold text-primary disabled:opacity-50"><RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} /> Aktualisieren</button>
        </div>

        <div className="surface-card flex items-center gap-3 p-4">
          <button disabled={!prospects.current || loadingProspects} onClick={() => openViewer("Aktuelles Prospekt", prospects.current)} className="min-w-0 flex-1 text-left disabled:opacity-45">
            <p className="text-sm font-semibold">Aktuelles Prospekt</p>
            <p className="text-xs text-muted-foreground">{loadingProspects ? "Prospekt wird gesucht…" : prospects.current ? `${dateRange(prospects.current)}${prospects.current.pageCount ? ` · ${prospects.current.pageCount} Seiten` : ""}` : "Kein direktes PDF erkannt"}</p>
          </button>
          {prospects.current ? <button onClick={() => openViewer("Aktuelles Prospekt", prospects.current)} className="rounded-full bg-primary-soft p-2 text-primary" aria-label="Im Viewer öffnen"><ExternalLink className="h-4 w-4" /></button> : detail.currentProspectUrl ? <a href={detail.currentProspectUrl} target="_blank" rel="noreferrer" className="rounded-full bg-secondary p-2 text-primary" aria-label="Beim Händler öffnen"><ExternalLink className="h-4 w-4" /></a> : null}
        </div>

        <div className="surface-card flex items-center gap-3 p-4">
          <button disabled={!prospects.next || loadingProspects} onClick={() => openViewer("Nächstes Prospekt", prospects.next)} className="min-w-0 flex-1 text-left disabled:opacity-45">
            <p className="text-sm font-semibold">Nächstes Prospekt</p>
            <p className="text-xs text-muted-foreground">{prospects.next ? `${dateRange(prospects.next)}${prospects.next.pageCount ? ` · ${prospects.next.pageCount} Seiten` : ""}` : "Noch nicht als PDF veröffentlicht oder erkannt"}</p>
          </button>
          {prospects.next ? <button onClick={() => openViewer("Nächstes Prospekt", prospects.next)} className="rounded-full bg-primary-soft p-2 text-primary" aria-label="Im Viewer öffnen"><ExternalLink className="h-4 w-4" /></button> : detail.futureProspectUrl ? <a href={detail.futureProspectUrl} target="_blank" rel="noreferrer" className="rounded-full bg-secondary p-2 text-primary" aria-label="Nächste Woche beim Händler prüfen"><ExternalLink className="h-4 w-4" /></a> : null}
        </div>
      </section>

      <section className="px-5 pt-6">
        <h2 className="text-base font-semibold">Anfahrt</h2>
        <div className="mt-3 grid grid-cols-3 gap-2">
          {[["Google Maps", detail.directions.google], ["Apple Karten", detail.directions.apple], ["OpenStreetMap", detail.directions.osm]].map(([label, url]) => url ? <a key={label} href={url!} target="_blank" rel="noreferrer" className="surface-card flex flex-col items-center gap-2 px-2 py-3 text-center text-xs font-semibold"><MapPinned className="h-5 w-5 text-primary" />{label}</a> : null)}
        </div>
      </section>

      {viewer && (
        <div className="fixed inset-0 z-[100] bg-black/70 p-2 backdrop-blur-sm sm:p-3">
          <div className="mx-auto flex h-full max-w-5xl flex-col overflow-hidden rounded-2xl bg-surface shadow-float">
            <header className="flex items-center gap-2 border-b border-border px-3 py-2.5 sm:px-4">
              <div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold">{viewer.label}</p><p className="truncate text-[11px] text-muted-foreground">{detail.name} · {dateRange(viewer.prospect)}</p></div>
              <a href={viewer.prospect.viewerUrl} target="_blank" rel="noreferrer" className="rounded-full bg-secondary p-2" aria-label="PDF extern öffnen"><ExternalLink className="h-4 w-4" /></a>
              <button onClick={() => setViewer(null)} className="rounded-full bg-primary p-2 text-primary-foreground" aria-label="Viewer schließen"><X className="h-5 w-5" /></button>
            </header>

            <div className="flex items-center justify-center gap-2 border-b border-border bg-surface-2 px-2 py-2">
              <button onClick={() => setViewer((v) => v ? { ...v, page: Math.max(1, v.page - 1) } : v)} disabled={viewer.page <= 1} className="rounded-full bg-surface p-2 disabled:opacity-35"><ChevronLeft className="h-4 w-4" /></button>
              <span className="min-w-20 text-center text-xs font-semibold tabular">{viewer.page}{viewer.prospect.pageCount ? ` / ${viewer.prospect.pageCount}` : ""}</span>
              <button onClick={() => setViewer((v) => v ? { ...v, page: v.prospect.pageCount ? Math.min(v.prospect.pageCount, v.page + 1) : v.page + 1 } : v)} disabled={Boolean(viewer.prospect.pageCount && viewer.page >= viewer.prospect.pageCount)} className="rounded-full bg-surface p-2 disabled:opacity-35"><ChevronRight className="h-4 w-4" /></button>
              <span className="mx-1 h-5 w-px bg-border" />
              <button onClick={() => setViewer((v) => v ? { ...v, zoom: Math.max(50, v.zoom - 25) } : v)} className="rounded-full bg-surface p-2"><Minus className="h-4 w-4" /></button>
              <span className="min-w-12 text-center text-xs font-semibold tabular">{viewer.zoom}%</span>
              <button onClick={() => setViewer((v) => v ? { ...v, zoom: Math.min(200, v.zoom + 25) } : v)} className="rounded-full bg-surface p-2"><Plus className="h-4 w-4" /></button>
            </div>

            <iframe key={viewerSrc} src={viewerSrc} title={viewer.label} className="min-h-0 flex-1 bg-white" />
            <p className="border-t border-border px-3 py-2 text-center text-[10px] text-muted-foreground">PDF wird von LocalPrices ausgeliefert. Mit X kommst du direkt zurück zum Markt.</p>
          </div>
        </div>
      )}
    </div>
  );
}

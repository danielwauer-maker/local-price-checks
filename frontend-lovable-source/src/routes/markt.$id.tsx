import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { ArrowLeft, ExternalLink, Heart, MapPinned, X } from "lucide-react";
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

function MarketDetailPage() {
  const { id } = Route.useParams();
  const { selected, toggleSelected, marketsInRadius } = useStore();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [viewer, setViewer] = useState<{ label: string; url: string } | null>(null);

  useEffect(() => {
    fetch(`/api/ux/stores/${id}`).then((r) => r.ok ? r.json() : Promise.reject()).then(setDetail).catch(() => setDetail(null));
  }, [id]);

  const market = marketsInRadius.find((m) => m.id === id);
  const chosen = selected.includes(id);

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
        <h2 className="text-base font-semibold">Prospekte</h2>
        <button disabled={!detail.currentProspectUrl} onClick={() => detail.currentProspectUrl && setViewer({ label: "Aktuelles Prospekt", url: detail.currentProspectUrl })} className="surface-card flex w-full items-center justify-between p-4 text-left disabled:opacity-45">
          <div><p className="text-sm font-semibold">Aktuelles Prospekt</p><p className="text-xs text-muted-foreground">Im Viewer ansehen</p></div><ExternalLink className="h-4 w-4 text-primary" />
        </button>
        <button disabled={!detail.futureProspectUrl} onClick={() => detail.futureProspectUrl && setViewer({ label: "Nächstes Prospekt", url: detail.futureProspectUrl })} className="surface-card flex w-full items-center justify-between p-4 text-left disabled:opacity-45">
          <div><p className="text-sm font-semibold">Nächstes Prospekt</p><p className="text-xs text-muted-foreground">{detail.futureProspectUrl ? "Sobald vom Händler veröffentlicht" : "Für diesen Händler noch nicht verfügbar"}</p></div><ExternalLink className="h-4 w-4 text-primary" />
        </button>
      </section>

      <section className="px-5 pt-6">
        <h2 className="text-base font-semibold">Anfahrt</h2>
        <div className="mt-3 grid grid-cols-3 gap-2">
          {[
            ["Google Maps", detail.directions.google],
            ["Apple Karten", detail.directions.apple],
            ["OpenStreetMap", detail.directions.osm],
          ].map(([label, url]) => url ? <a key={label} href={url!} target="_blank" rel="noreferrer" className="surface-card flex flex-col items-center gap-2 px-2 py-3 text-center text-xs font-semibold"><MapPinned className="h-5 w-5 text-primary" />{label}</a> : null)}
        </div>
      </section>

      {viewer && (
        <div className="fixed inset-0 z-[100] bg-black/60 p-3 backdrop-blur-sm">
          <div className="mx-auto flex h-full max-w-4xl flex-col overflow-hidden rounded-2xl bg-surface shadow-float">
            <header className="flex items-center gap-3 border-b border-border px-4 py-3">
              <div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold">{viewer.label}</p><p className="truncate text-[11px] text-muted-foreground">{detail.name}</p></div>
              <a href={viewer.url} target="_blank" rel="noreferrer" className="rounded-full bg-secondary p-2" aria-label="Extern öffnen"><ExternalLink className="h-4 w-4" /></a>
              <button onClick={() => setViewer(null)} className="rounded-full bg-primary p-2 text-primary-foreground" aria-label="Viewer schließen"><X className="h-5 w-5" /></button>
            </header>
            <iframe src={viewer.url} title={viewer.label} className="min-h-0 flex-1 bg-white" />
            <p className="border-t border-border px-4 py-2 text-[11px] text-muted-foreground">Falls der Händler das Einbetten blockiert, nutze oben „extern öffnen“. Mit X kommst du direkt zurück in die App.</p>
          </div>
        </div>
      )}
    </div>
  );
}

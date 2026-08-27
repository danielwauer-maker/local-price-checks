import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { ArrowRight, Check, ChevronDown, ChevronRight, Clock3, ListChecks, Mic, Minus, Plus, Save, Search, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/AppShell";
import { Tabs } from "@/components/lokero/FilterChips";
import { OptimizedTripSummary, ShoppingMarketGroup, TripRouteRow } from "@/components/lokero/OptimizedTrip";
import { ProductImage } from "@/components/lokero/ProductImage";
import { MarketLogo } from "@/components/lokero/MarketLogo";
import { EmptyState, ErrorState, SkeletonList } from "@/components/lokero/States";
import { manualListKey, useStore } from "@/lib/app-store";
import { bestPriceFor, fetchFeatures, fetchOptimizedTrip, getMarket, getProduct } from "@/services/lokero-api";
import { formatEuro, formatKm } from "@/lib/format";

export const Route = createFileRoute("/liste")({
  head: () => ({ meta: [{ title: "Einkaufsliste – Spareno" }] }),
  component: ListScreen,
});

const TABS = [{ id: "meine", label: "Liste" }, { id: "optimiert", label: "Optimiert" }];
const SWIPE_THRESHOLD = 64;

type ListGroup = {
  key: string;
  marketId?: string;
  marketName: string;
  distanceKm: number;
  subtotal: number | null;
  entries: Array<{ productId: string; qty: number; price?: number }>;
};

type SpeechRecognitionResultLike = {
  0?: { transcript?: string };
};

type SpeechRecognitionEventLike = {
  results?: ArrayLike<SpeechRecognitionResultLike>;
};

type SpeechRecognitionLike = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  start: () => void;
  stop: () => void;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
};

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

function SwipeableRow({ children, onCheck, onDelete, checked }: { children: ReactNode; onCheck: () => void; onDelete: () => void; checked: boolean }) {
  const startX = useRef<number | null>(null);
  const [offset, setOffset] = useState(0);

  const reset = () => {
    startX.current = null;
    setOffset(0);
  };

  return (
    <div className="relative overflow-hidden bg-surface">
      <div className="absolute inset-y-0 left-0 flex w-24 items-center justify-start bg-primary-soft pl-4 text-primary" aria-hidden="true">
        <Check className="h-5 w-5" />
      </div>
      <div className="absolute inset-y-0 right-0 flex w-24 items-center justify-end bg-destructive/10 pr-4 text-destructive" aria-hidden="true">
        <Trash2 className="h-5 w-5" />
      </div>
      <div
        className="relative bg-surface transition-transform duration-150"
        style={{ transform: `translateX(${offset}px)` }}
        onTouchStart={(event) => {
          startX.current = event.touches[0]?.clientX ?? null;
        }}
        onTouchMove={(event) => {
          if (startX.current == null) return;
          const currentX = event.touches[0]?.clientX;
          if (currentX == null) return;
          const delta = currentX - startX.current;
          setOffset(Math.max(-96, Math.min(96, delta)));
        }}
        onTouchEnd={() => {
          if (offset >= SWIPE_THRESHOLD) onCheck();
          if (offset <= -SWIPE_THRESHOLD) onDelete();
          reset();
        }}
        onTouchCancel={reset}
        aria-label={checked ? "Erledigter Listeneintrag" : "Offener Listeneintrag"}
      >
        {children}
      </div>
    </div>
  );
}

function ListScreen() {
  const [tab, setTab] = useState("meine");
  const [manualName, setManualName] = useState("");
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => new Set());
  const [isListening, setIsListening] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const {
    listEntries,
    manualListItems,
    checkedListItems,
    setQty,
    addToList,
    addManualListItem,
    setManualListQty,
    removeManualListItem,
    clearList,
    toggleListChecked,
  } = useStore();
  const features = useQuery({ queryKey: ["lokero-features"], queryFn: fetchFeatures });
  const trip = useQuery({ queryKey: ["optimized-trip"], queryFn: fetchOptimizedTrip });
  const optimizationEnabled = features.data?.features.optimization !== false && trip.data?.enabled !== false;

  const groups = useMemo<ListGroup[]>(() => {
    const byMarket = new Map<string, ListGroup>();
    const unknown: ListGroup = { key: "unknown", marketName: "Noch kein Marktpreis", distanceKm: Number.POSITIVE_INFINITY, subtotal: null, entries: [] };
    for (const entry of listEntries) {
      const best = bestPriceFor(entry.productId);
      const market = best ? getMarket(best.marketId) : undefined;
      if (!best || !market) {
        unknown.entries.push(entry);
        continue;
      }
      const existing = byMarket.get(market.id) ?? { key: market.id, marketId: market.id, marketName: market.name, distanceKm: market.distanceKm, subtotal: 0, entries: [] };
      existing.entries.push({ ...entry, price: best.price });
      existing.subtotal = (existing.subtotal ?? 0) + best.price * entry.qty;
      byMarket.set(market.id, existing);
    }
    const result = Array.from(byMarket.values()).sort((a, b) => a.distanceKm - b.distanceKm);
    if (unknown.entries.length) result.push(unknown);
    return result;
  }, [listEntries]);

  const totalPositions = listEntries.length + manualListItems.length;
  const hasAnyItems = totalPositions > 0;
  const checkedManualCount = manualListItems.filter((item) => checkedListItems.includes(manualListKey(item.id))).length;

  const changeTab = (nextTab: string) => setTab(nextTab);

  const confirmClearList = () => {
    if (!window.confirm("Möchtest du wirklich die komplette Einkaufsliste leeren?")) return;
    clearList();
    toast.success("Liste geleert");
  };

  const submitManualItem = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const name = manualName.trim();
    if (!name) return;
    addManualListItem(name);
    setManualName("");
    toast.success(`${name} hinzugefügt`);
  };

  const toggleGroup = (key: string) => {
    setCollapsedGroups((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const startVoiceInput = () => {
    if (typeof window === "undefined") return;

    const isIOS = /iPad|iPhone|iPod/.test(window.navigator.userAgent)
      || (window.navigator.platform === "MacIntel" && window.navigator.maxTouchPoints > 1);
    if (isIOS) {
      toast.info("Spracheingabe ist auf iPhone und iPad aktuell deaktiviert. Du kannst Artikel weiterhin über die iOS-Diktierfunktion der Tastatur einsprechen.");
      return;
    }

    const speechWindow = window as typeof window & {
      SpeechRecognition?: SpeechRecognitionConstructor;
      webkitSpeechRecognition?: SpeechRecognitionConstructor;
    };
    const Recognition = speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition;
    if (!Recognition) {
      toast.info("Spracheingabe wird von diesem Browser leider nicht unterstützt.");
      return;
    }
    if (isListening) {
      try {
        recognitionRef.current?.stop();
      } catch {
        recognitionRef.current = null;
        setIsListening(false);
      }
      return;
    }

    try {
      const recognition = new Recognition();
      recognition.lang = "de-DE";
      recognition.interimResults = false;
      recognition.continuous = false;
      recognition.onresult = (event) => {
        const transcript = event.results?.[0]?.[0]?.transcript?.trim();
        if (!transcript) return;
        const names = transcript.split(/,| und /i).map((item) => item.trim()).filter(Boolean).slice(0, 10);
        names.forEach((name) => addManualListItem(name));
        toast.success(names.length > 1 ? `${names.length} Artikel hinzugefügt` : `${names[0]} hinzugefügt`);
      };
      recognition.onerror = () => {
        setIsListening(false);
        recognitionRef.current = null;
        toast.error("Spracheingabe konnte nicht erkannt werden.");
      };
      recognition.onend = () => {
        setIsListening(false);
        recognitionRef.current = null;
      };
      recognitionRef.current = recognition;
      recognition.start();
      setIsListening(true);
    } catch {
      recognitionRef.current = null;
      setIsListening(false);
      toast.error("Spracheingabe konnte nicht gestartet werden.");
    }
  };

  return (
    <div>
      <PageHeader title="Einkaufsliste" action={hasAnyItems ? <button type="button" onClick={confirmClearList} className="tap-target grid place-items-center rounded-xl text-muted-foreground" aria-label="Liste leeren"><Trash2 className="h-4.5 w-4.5" /></button> : undefined} />
      <div className="bg-surface px-4"><Tabs options={TABS} value={tab} onChange={changeTab} /></div>

      {tab === "optimiert" && (
        <div className="space-y-3 px-4 pt-4">
          {(features.isLoading || trip.isLoading) && <SkeletonList count={3} />}
          {trip.isError && <ErrorState onRetry={() => trip.refetch()} />}
          {!features.isLoading && !trip.isLoading && !optimizationEnabled && (
            <section className="card-surface p-5 text-center">
              <span className="mx-auto grid h-10 w-10 place-items-center rounded-xl bg-primary-soft text-primary"><Clock3 className="h-5 w-5" /></span>
              <h2 className="mt-3 text-[15px] font-semibold text-navy">Einkaufsoptimierung wird vorbereitet</h2>
              <p className="mx-auto mt-1 max-w-[300px] text-[12px] leading-relaxed text-muted-foreground">Deine Einkaufsliste funktioniert bereits. Sobald mehrere geprüfte Märkte und belastbare Vergleichspreise verfügbar sind, schaltet Spareno die optimale Marktkombination frei.</p>
              <button type="button" onClick={() => changeTab("meine")} className="mt-4 h-11 rounded-xl bg-primary px-4 text-[13px] font-semibold text-primary-foreground">Liste ansehen</button>
            </section>
          )}
          {optimizationEnabled && trip.data && <><OptimizedTripSummary trip={trip.data} /><TripRouteRow trip={trip.data} />{trip.data.stops.map((s) => <ShoppingMarketGroup key={s.marketId} stop={s} />)}<button type="button" onClick={() => toast.success("Route wird in deiner Karten-App geöffnet")} className="flex h-13 w-full items-center justify-center gap-2 rounded-xl bg-primary py-3.5 text-[15px] font-semibold text-primary-foreground">Route & Einkauf starten <ArrowRight className="h-4 w-4" /></button><button type="button" onClick={() => toast.success("Liste gespeichert")} className="flex w-full items-center justify-center gap-2 py-1 text-[13px] font-medium text-muted-foreground"><Save className="h-4 w-4" /> Liste speichern</button></>}
        </div>
      )}

      {tab === "meine" && (
        <div className="space-y-4 px-4 pt-4">
          <form onSubmit={submitManualItem} className="rounded-2xl border border-border bg-surface p-3">
            <label htmlFor="manual-list-item" className="mb-2 block text-[12px] font-semibold text-navy">Artikel frei hinzufügen</label>
            <div className="flex gap-2">
              <input id="manual-list-item" value={manualName} onChange={(event) => setManualName(event.target.value)} placeholder="z. B. Milch, Müllbeutel …" maxLength={80} autoComplete="off" enterKeyHint="done" className="h-11 min-w-0 flex-1 rounded-xl border border-border bg-muted-surface px-3 text-[13px] text-navy outline-none placeholder:text-muted-foreground focus:border-primary" />
              <button type="button" onClick={startVoiceInput} className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl border ${isListening ? "border-primary bg-primary-soft text-primary" : "border-border bg-surface text-muted-foreground"}`} aria-label={isListening ? "Spracheingabe beenden" : "Artikel per Sprache hinzufügen"}><Mic className="h-4 w-4" /></button>
              <button type="submit" disabled={!manualName.trim()} className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-primary text-primary-foreground disabled:opacity-40" aria-label="Freien Artikel hinzufügen"><Plus className="h-4 w-4" /></button>
            </div>
            <p className="mt-2 text-[10px] leading-relaxed text-muted-foreground">Tippen oder sprechen. Freie Artikel bleiben auf diesem Gerät gespeichert.</p>
          </form>

          {!hasAnyItems && <EmptyState icon={ListChecks} title="Deine Einkaufsliste ist noch leer." description="Füge oben einen freien Artikel ein oder übernimm Produkte direkt aus den Angeboten." action={<div className="flex flex-wrap justify-center gap-2"><Link to="/angebote" className="inline-flex h-11 items-center gap-1.5 rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground"><Plus className="h-4 w-4" /> Angebote ansehen</Link><Link to="/suche" className="inline-flex h-11 items-center gap-1.5 rounded-xl border border-border bg-surface px-4 text-sm font-semibold text-navy"><Search className="h-4 w-4" /> Produkt suchen</Link></div>} />}

          {groups.map((group) => {
            const market = group.marketId ? getMarket(group.marketId) : undefined;
            const collapsed = collapsedGroups.has(group.key);
            const checkedInGroup = group.entries.filter((entry) => checkedListItems.includes(entry.productId)).length;
            const displayEntries = [...group.entries].sort((a, b) => Number(checkedListItems.includes(a.productId)) - Number(checkedListItems.includes(b.productId)));
            return (
              <section key={group.key} className="overflow-hidden rounded-2xl border border-border bg-surface">
                <button type="button" onClick={() => toggleGroup(group.key)} className="flex w-full items-center gap-3 border-b border-border bg-muted-surface/70 px-3 py-3 text-left" aria-expanded={!collapsed}>
                  {market && <MarketLogo chain={market.chain} size="sm" />}
                  <div className="min-w-0 flex-1">
                    <h2 className="line-clamp-2 text-[13px] font-semibold leading-snug text-navy">{group.marketName}</h2>
                    <p className="mt-0.5 text-[10px] text-muted-foreground">{group.entries.length} Artikel{market ? ` · ${formatKm(group.distanceKm)}` : ""}</p>
                  </div>
                  {group.subtotal != null && <div className="shrink-0 text-right"><p className="text-[10px] text-muted-foreground">Zwischensumme</p><p className="tabular text-[14px] font-bold text-navy">{formatEuro(group.subtotal)}</p></div>}
                  <span className="ml-1 grid h-8 w-8 shrink-0 place-items-center rounded-lg text-muted-foreground" aria-hidden="true">{collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}</span>
                </button>
                {!collapsed && (
                  <div className="divide-y divide-border">
                    {displayEntries.map(({ productId, qty, price }) => {
                      const product = getProduct(productId);
                      if (!product) return null;
                      const checked = checkedListItems.includes(productId);
                      return (
                        <SwipeableRow key={productId} checked={checked} onCheck={() => toggleListChecked(productId)} onDelete={() => { setQty(productId, 0); toast.success(`${product.name} entfernt`); }}>
                          <article className={`flex items-center gap-2.5 p-3 transition-opacity ${checked ? "opacity-55" : ""}`}>
                            <button type="button" onClick={() => toggleListChecked(productId)} aria-label={checked ? `${product.name} wieder öffnen` : `${product.name} abhaken`} className={`grid h-7 w-7 shrink-0 place-items-center rounded-full border-2 ${checked ? "border-primary bg-primary text-primary-foreground" : "border-border bg-surface text-transparent"}`}><Check className="h-3.5 w-3.5" /></button>
                            <ProductImage product={product} size="sm" />
                            <button type="button" onClick={() => toggleListChecked(productId)} className="min-w-0 flex-1 text-left">
                              <p className={`line-clamp-2 text-[13px] font-semibold leading-snug text-navy ${checked ? "line-through" : ""}`}>{product.name}</p>
                              <p className="tabular mt-1 text-[11px] text-muted-foreground">{qty > 1 ? `${qty} Stück` : "1 Stück"}{price != null ? ` · ${formatEuro(price)} je Stück` : ""}</p>
                            </button>
                            <div className={`flex shrink-0 items-center gap-1 rounded-xl bg-muted-surface p-1 ${checked ? "opacity-45" : ""}`} aria-disabled={checked}>
                              <button type="button" disabled={checked} onClick={() => setQty(productId, qty - 1)} aria-label="Menge verringern" className="grid h-8 w-8 place-items-center rounded-lg bg-surface text-navy disabled:cursor-not-allowed disabled:text-muted-foreground"><Minus className="h-3.5 w-3.5" /></button>
                              <span className="tabular w-5 text-center text-[13px] font-semibold">{qty}</span>
                              <button type="button" disabled={checked} onClick={() => addToList(productId)} aria-label="Menge erhöhen" className="grid h-8 w-8 place-items-center rounded-lg bg-surface text-navy disabled:cursor-not-allowed disabled:text-muted-foreground"><Plus className="h-3.5 w-3.5" /></button>
                            </div>
                          </article>
                        </SwipeableRow>
                      );
                    })}
                    {checkedInGroup > 0 && <p className="px-3 py-2 text-[10px] text-muted-foreground">{checkedInGroup} von {group.entries.length} erledigt · erledigte Artikel stehen unten</p>}
                  </div>
                )}
              </section>
            );
          })}

          {manualListItems.length > 0 && (() => {
            const key = "manual";
            const collapsed = collapsedGroups.has(key);
            const sortedItems = [...manualListItems].sort((a, b) => Number(checkedListItems.includes(manualListKey(a.id))) - Number(checkedListItems.includes(manualListKey(b.id))));
            return (
              <section className="overflow-hidden rounded-2xl border border-border bg-surface">
                <button type="button" onClick={() => toggleGroup(key)} className="flex w-full items-center justify-between gap-3 border-b border-border bg-muted-surface/70 px-3 py-3 text-left" aria-expanded={!collapsed}>
                  <div><h2 className="text-[13px] font-semibold text-navy">Weitere Artikel</h2><p className="text-[10px] text-muted-foreground">{manualListItems.length} Artikel · ohne Preisvergleich</p></div>
                  <div className="flex items-center gap-2"><span className="text-[11px] font-medium text-muted-foreground">{checkedManualCount}/{manualListItems.length}</span>{collapsed ? <ChevronRight className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}</div>
                </button>
                {!collapsed && (
                  <div className="divide-y divide-border">
                    {sortedItems.map((item) => {
                      const itemKey = manualListKey(item.id);
                      const checked = checkedListItems.includes(itemKey);
                      return (
                        <SwipeableRow key={item.id} checked={checked} onCheck={() => toggleListChecked(itemKey)} onDelete={() => { removeManualListItem(item.id); toast.success(`${item.name} entfernt`); }}>
                          <article className={`flex items-center gap-2.5 p-3 transition-opacity ${checked ? "opacity-55" : ""}`}>
                            <button type="button" onClick={() => toggleListChecked(itemKey)} aria-label={checked ? `${item.name} wieder öffnen` : `${item.name} abhaken`} className={`grid h-7 w-7 shrink-0 place-items-center rounded-full border-2 ${checked ? "border-primary bg-primary text-primary-foreground" : "border-border bg-surface text-transparent"}`}><Check className="h-3.5 w-3.5" /></button>
                            <button type="button" onClick={() => toggleListChecked(itemKey)} className="min-w-0 flex-1 text-left"><p className={`line-clamp-2 text-[13px] font-semibold leading-snug text-navy ${checked ? "line-through" : ""}`}>{item.name}</p><p className="mt-1 text-[11px] text-muted-foreground">{item.qty > 1 ? `${item.qty} Stück` : "1 Stück"}</p></button>
                            <div className={`flex shrink-0 items-center gap-1 rounded-xl bg-muted-surface p-1 ${checked ? "opacity-45" : ""}`} aria-disabled={checked}>
                              <button type="button" disabled={checked} onClick={() => setManualListQty(item.id, item.qty - 1)} aria-label="Menge verringern" className="grid h-8 w-8 place-items-center rounded-lg bg-surface text-navy disabled:cursor-not-allowed disabled:text-muted-foreground"><Minus className="h-3.5 w-3.5" /></button>
                              <span className="tabular w-5 text-center text-[13px] font-semibold">{item.qty}</span>
                              <button type="button" disabled={checked} onClick={() => setManualListQty(item.id, item.qty + 1)} aria-label="Menge erhöhen" className="grid h-8 w-8 place-items-center rounded-lg bg-surface text-navy disabled:cursor-not-allowed disabled:text-muted-foreground"><Plus className="h-3.5 w-3.5" /></button>
                            </div>
                          </article>
                        </SwipeableRow>
                      );
                    })}
                  </div>
                )}
              </section>
            );
          })()}
        </div>
      )}
    </div>
  );
}
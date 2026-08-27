import {
  ArrowLeft,
  ArrowRight,
  BellRing,
  Check,
  Heart,
  MapPin,
  QrCode,
  Search,
  Share2,
  ShoppingBasket,
  Sparkles,
  Store,
  Tag,
  TrendingDown,
  Users,
} from "lucide-react";
import { useEffect, useRef, useState, type PointerEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";

export const SPARENO_ONBOARDING_STORAGE_KEY = "spareno_onboarding_v1_completed";
export const SPARENO_ONBOARDING_REPLAY_EVENT = "spareno:onboarding:replay";

const SWIPE_THRESHOLD_PX = 54;

type OnboardingCard = {
  eyebrow: string;
  title: string;
  text: string;
  visual: ReactNode;
  titleClassName?: string;
};

function MapVisual() {
  return (
    <div className="relative h-full w-full overflow-hidden rounded-[1.65rem] border border-primary/10 bg-primary/[0.045] p-4" aria-hidden="true">
      <div className="absolute inset-0 opacity-50" style={{ backgroundImage: "linear-gradient(to right, hsl(var(--border)) 1px, transparent 1px), linear-gradient(to bottom, hsl(var(--border)) 1px, transparent 1px)", backgroundSize: "34px 34px" }} />
      <div className="absolute left-[12%] top-[58%] h-1.5 w-[78%] -rotate-6 rounded-full bg-primary/10" />
      <div className="absolute left-[24%] top-[18%] h-[70%] w-1.5 rotate-[28deg] rounded-full bg-primary/10" />
      <div className="absolute left-[58%] top-[16%] h-[70%] w-1.5 -rotate-[18deg] rounded-full bg-primary/10" />
      <div className="absolute left-[15%] top-[22%] grid h-10 w-10 place-items-center rounded-2xl bg-surface shadow-sm ring-1 ring-border"><Store className="h-5 w-5 text-primary" /></div>
      <div className="absolute right-[14%] top-[30%] grid h-10 w-10 place-items-center rounded-2xl bg-surface shadow-sm ring-1 ring-border"><MapPin className="h-5 w-5 text-primary" /></div>
      <div className="absolute bottom-[18%] left-[43%] grid h-11 w-11 place-items-center rounded-full bg-primary text-primary-foreground shadow-lg ring-4 ring-primary/10"><MapPin className="h-5 w-5" fill="currentColor" /></div>
      <div className="absolute bottom-3 right-3 rounded-xl bg-surface/95 px-3 py-2 text-left shadow-sm ring-1 ring-border"><p className="text-[9px] font-medium text-muted-foreground">In deiner Nähe</p><p className="mt-0.5 text-[11px] font-semibold text-navy">3 Märkte gefunden</p></div>
    </div>
  );
}

function OffersVisual() {
  return (
    <div className="flex h-full w-full flex-col justify-center rounded-[1.65rem] border border-primary/10 bg-primary/[0.045] p-4" aria-hidden="true">
      <div className="mx-auto mb-3 flex h-10 w-[88%] items-center gap-2 rounded-xl border border-border bg-surface px-3 shadow-sm"><Search className="h-4 w-4 text-primary" /><span className="text-[11px] text-muted-foreground">Cola, Käse, Fisch …</span></div>
      <div className="grid grid-cols-3 gap-2.5">
        {["Cola", "Käse", "Kaffee"].map((name, index) => (
          <div key={name} className="relative rounded-2xl border border-border bg-surface p-2.5 shadow-sm">
            <div className="grid h-11 place-items-center rounded-xl bg-muted-surface">{index === 0 ? <ShoppingBasket className="h-5 w-5 text-primary" /> : index === 1 ? <Tag className="h-5 w-5 text-primary" /> : <Sparkles className="h-5 w-5 text-primary" />}</div>
            <p className="mt-2 truncate text-[10px] font-semibold text-navy">{name}</p>
            <p className="mt-0.5 text-[12px] font-bold text-primary">{["1,29 €", "1,79 €", "4,99 €"][index]}</p>
            <span className="absolute right-1.5 top-1.5 rounded-full bg-primary px-1.5 py-0.5 text-[8px] font-bold text-primary-foreground">Deal</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function SharedListVisual() {
  const rows = ["Milch", "Tomaten", "Müllbeutel"];
  return (
    <div className="h-full w-full rounded-[1.65rem] border border-primary/10 bg-primary/[0.045] p-4" aria-hidden="true">
      <div className="mx-auto h-full max-w-[300px] overflow-hidden rounded-2xl border border-border bg-surface shadow-sm">
        <div className="flex items-center justify-between bg-muted-surface px-3 py-2.5">
          <div className="flex items-center gap-2"><Users className="h-4 w-4 text-primary" /><span className="text-[11px] font-semibold text-navy">Familieneinkauf</span></div>
          <div className="flex -space-x-1"><span className="grid h-5 w-5 place-items-center rounded-full border border-surface bg-primary text-[8px] font-bold text-primary-foreground">D</span><span className="grid h-5 w-5 place-items-center rounded-full border border-surface bg-primary-soft text-[8px] font-bold text-primary">J</span></div>
        </div>
        <div className="divide-y divide-border">
          {rows.map((row, index) => (
            <div key={row} className="flex items-center gap-2.5 px-3 py-2.5">
              <span className={`grid h-5 w-5 shrink-0 place-items-center rounded-full border-2 ${index === 0 ? "border-primary bg-primary text-primary-foreground" : "border-border"}`}>{index === 0 && <Check className="h-3 w-3" />}</span>
              <span className={`flex-1 text-[11px] font-medium text-navy ${index === 0 ? "line-through opacity-50" : ""}`}>{row}</span>
              <span className="text-[8px] text-muted-foreground">{index === 1 ? "von Jenny" : index === 0 ? "erledigt" : "live"}</span>
            </div>
          ))}
        </div>
        <div className="flex items-center justify-center gap-1.5 border-t border-border bg-primary/[0.04] py-2 text-[9px] font-semibold text-primary"><span className="h-1.5 w-1.5 rounded-full bg-success" />Live synchronisiert</div>
      </div>
    </div>
  );
}

function FavoriteShareVisual() {
  return (
    <div className="h-full w-full rounded-[1.65rem] border border-primary/10 bg-primary/[0.045] p-4" aria-hidden="true">
      <div className="mx-auto flex h-full max-w-[310px] items-center gap-3">
        <div className="min-w-0 flex-1 rounded-2xl border border-border bg-surface p-3 shadow-sm">
          <div className="flex items-center gap-2"><Heart className="h-4 w-4 fill-discount text-discount" /><p className="text-[11px] font-semibold text-navy">Jennys Favoriten</p></div>
          <div className="mt-3 space-y-2">
            {["Coca-Cola", "Kaffee", "Schokolade"].map((name, index) => <div key={name} className="flex items-center gap-2 rounded-xl bg-muted-surface px-2.5 py-2"><span className="grid h-7 w-7 place-items-center rounded-lg bg-surface"><Heart className="h-3.5 w-3.5 fill-primary/15 text-primary" /></span><span className="min-w-0 flex-1 truncate text-[9px] font-semibold text-navy">{name}</span>{index === 0 && <BellRing className="h-3.5 w-3.5 text-discount" />}</div>)}
          </div>
        </div>
        <div className="flex w-[86px] shrink-0 flex-col items-center gap-2">
          <div className="grid h-[72px] w-[72px] place-items-center rounded-2xl border border-border bg-surface shadow-sm"><QrCode className="h-10 w-10 text-navy" /></div>
          <div className="flex items-center gap-1 rounded-full bg-primary px-2.5 py-1 text-[8px] font-bold text-primary-foreground"><Share2 className="h-3 w-3" />Teilen</div>
        </div>
      </div>
    </div>
  );
}

function SavingsVisual() {
  return (
    <div className="h-full w-full rounded-[1.65rem] border border-primary/10 bg-primary/[0.045] p-4" aria-hidden="true">
      <div className="mx-auto grid h-full max-w-[300px] grid-cols-[1fr_auto_1fr] items-center gap-2">
        <div className="rounded-2xl border border-border bg-surface p-3 text-center shadow-sm"><Store className="mx-auto h-5 w-5 text-muted-foreground" /><p className="mt-2 text-[10px] font-semibold text-navy">Markt A</p><p className="mt-1 text-[15px] font-bold text-navy">28,40 €</p></div>
        <TrendingDown className="h-5 w-5 text-primary" />
        <div className="rounded-2xl border border-primary/20 bg-surface p-3 text-center shadow-sm ring-2 ring-primary/5"><Store className="mx-auto h-5 w-5 text-primary" /><p className="mt-2 text-[10px] font-semibold text-navy">Bessere Wahl</p><p className="mt-1 text-[15px] font-bold text-primary">23,10 €</p></div>
      </div>
      <div className="mx-auto -mt-7 flex w-fit items-center gap-2 rounded-full bg-primary px-3 py-1.5 text-primary-foreground shadow-sm"><Sparkles className="h-3.5 w-3.5" /><span className="text-[10px] font-bold">5,30 € sparen</span></div>
    </div>
  );
}

const CARDS: OnboardingCard[] = [
  {
    eyebrow: "Deine Umgebung",
    title: "Lokale Märkte in deiner Nähe",
    text: "Entdecke Angebote aus Märkten in deiner Umgebung. Spareno zeigt dir, welche Händler in deiner Region bereits verfügbar sind.",
    visual: <MapVisual />,
    titleClassName: "max-w-[16ch]",
  },
  {
    eyebrow: "Angebote entdecken",
    title: "Finde Angebote schneller",
    text: "Suche gezielt nach Produkten oder Kategorien wie Cola, Käse oder Fisch und entdecke passende Angebote auf einen Blick.",
    visual: <OffersVisual />,
  },
  {
    eyebrow: "Gemeinsam einkaufen",
    title: "Eine Liste für euch alle",
    text: "Teile Einkaufslisten mit Partnern, Familie oder Freunden. Hinzufügen und Abhaken wird bei allen fast sofort aktualisiert.",
    visual: <SharedListVisual />,
  },
  {
    eyebrow: "Freude machen",
    title: "Teile deine Favoriten",
    text: "Gib ausgewählte Lieblingsprodukte per Link oder QR-Code frei und speichere Favoriten von Freunden direkt in Spareno.",
    visual: <FavoriteShareVisual />,
  },
  {
    eyebrow: "Clever vergleichen",
    title: "Besser sparen mit Spareno",
    text: "Vergleiche Angebote und sieh, wo dein Einkauf günstiger wird. Spareno hilft dir, langfristig die bessere Wahl zu treffen.",
    visual: <SavingsVisual />,
  },
];

function onboardingAlreadyCompleted(): boolean {
  if (typeof window === "undefined") return true;
  try {
    return window.localStorage.getItem(SPARENO_ONBOARDING_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function rememberCompletion(): void {
  try {
    window.localStorage.setItem(SPARENO_ONBOARDING_STORAGE_KEY, "1");
  } catch {
    // Storage may be unavailable in privacy-restricted contexts. Closing the overlay still works.
  }
}

export function FirstStartOnboarding({ active = true }: { active?: boolean }) {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);
  const initialized = useRef(false);
  const pointerStartX = useRef<number | null>(null);

  useEffect(() => {
    const replay = () => {
      setStep(0);
      setOpen(true);
    };
    window.addEventListener(SPARENO_ONBOARDING_REPLAY_EVENT, replay);
    return () => window.removeEventListener(SPARENO_ONBOARDING_REPLAY_EVENT, replay);
  }, []);

  useEffect(() => {
    if (!active || initialized.current) return;
    initialized.current = true;
    setOpen(!onboardingAlreadyCompleted());
  }, [active]);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previousOverflow; };
  }, [open]);

  if (!open || typeof document === "undefined") return null;

  const lastStep = step === CARDS.length - 1;
  const card = CARDS[step];
  const complete = () => { rememberCompletion(); setOpen(false); };
  const previous = () => setStep((current) => Math.max(0, current - 1));
  const next = () => {
    if (lastStep) complete();
    else setStep((current) => Math.min(CARDS.length - 1, current + 1));
  };

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if ((event.target as HTMLElement).closest("button")) return;
    pointerStartX.current = event.clientX;
  };

  const handlePointerUp = (event: PointerEvent<HTMLDivElement>) => {
    if (pointerStartX.current === null) return;
    const delta = event.clientX - pointerStartX.current;
    pointerStartX.current = null;
    if (delta <= -SWIPE_THRESHOLD_PX) next();
    if (delta >= SWIPE_THRESHOLD_PX && step > 0) previous();
  };

  return createPortal(
    <div className="fixed inset-0 isolate bg-background" style={{ zIndex: 2147483647 }} role="dialog" aria-modal="true" aria-label="Einführung in Spareno">
      <div className="mx-auto flex h-[100dvh] w-full max-w-[480px] flex-col overflow-hidden bg-background px-4 pb-[max(0.9rem,env(safe-area-inset-bottom))] pt-[max(0.75rem,env(safe-area-inset-top))] sm:px-5">
        <div className="flex h-11 shrink-0 items-center justify-between">
          <div className="font-display text-[17px] font-semibold tracking-tight text-primary">Spareno</div>
          <button type="button" onClick={complete} className="rounded-full px-3 py-2 text-[12px] font-semibold text-muted-foreground transition-colors hover:bg-muted-surface hover:text-navy">Überspringen</button>
        </div>

        <div className="flex min-h-0 flex-1 touch-pan-y select-none flex-col" onPointerDown={handlePointerDown} onPointerUp={handlePointerUp} onPointerCancel={() => { pointerStartX.current = null; }}>
          <div className="mx-auto mt-1 h-[min(28dvh,198px)] min-h-[152px] w-full max-w-[382px] shrink-0">{card.visual}</div>
          <div className="mx-auto flex min-h-0 w-full max-w-[390px] flex-1 flex-col items-center justify-start px-1 pb-2 pt-[clamp(1.45rem,4.2dvh,2.6rem)] text-center">
            <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-primary">{card.eyebrow}</p>
            <h1 className={`mx-auto mt-2 font-display text-[clamp(1.24rem,2.7dvh,1.62rem)] font-semibold leading-[1.08] tracking-tight text-navy ${card.titleClassName ?? ""}`}>{card.title}</h1>
            <p className="mx-auto mt-3 max-w-[35ch] text-[clamp(0.76rem,1.55dvh,0.9rem)] leading-[1.5] text-muted-foreground">{card.text}</p>
          </div>
        </div>

        <div className="shrink-0 space-y-3 pt-1">
          <div className="flex justify-center gap-2" aria-label={`Schritt ${step + 1} von ${CARDS.length}`}>
            {CARDS.map((item, index) => <button key={item.title} type="button" onClick={() => setStep(index)} aria-label={`Zu Schritt ${index + 1}`} aria-current={index === step ? "step" : undefined} className={`h-2 rounded-full transition-all duration-200 ${index === step ? "w-7 bg-primary" : "w-2 bg-border"}`} />)}
          </div>
          <div className="flex gap-2.5">
            <button type="button" onClick={previous} disabled={step === 0} className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl border border-border bg-surface text-navy shadow-sm transition-colors hover:bg-muted-surface disabled:pointer-events-none disabled:opacity-0" aria-label="Zurück"><ArrowLeft className="h-4.5 w-4.5" /></button>
            <button type="button" onClick={next} className="flex h-12 flex-1 items-center justify-center gap-2 rounded-2xl bg-primary px-5 text-[13px] font-semibold text-primary-foreground shadow-sm transition-transform active:scale-[0.99]">{lastStep ? "Los geht’s" : "Weiter"}<ArrowRight className="h-4 w-4" /></button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

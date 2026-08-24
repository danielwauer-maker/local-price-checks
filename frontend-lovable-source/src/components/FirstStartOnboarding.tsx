import {
  ArrowLeft,
  ArrowRight,
  Heart,
  ListChecks,
  MapPinned,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useRef, useState, type PointerEvent } from "react";

const STORAGE_KEY = "lp_onboarding_v1_completed";
const SWIPE_THRESHOLD_PX = 56;

type OnboardingCard = {
  eyebrow: string;
  title: string;
  text: string;
  icon: LucideIcon;
};

const CARDS: OnboardingCard[] = [
  {
    eyebrow: "Willkommen bei LocalPrices",
    title: "Dein Preisradar für die Umgebung",
    text: "Vergleiche lokale Wochenangebote und sieh auf einen Blick, wo sich dein Einkauf wirklich lohnt.",
    icon: Sparkles,
  },
  {
    eyebrow: "Märkte in deiner Nähe",
    title: "Du bestimmst, welche Märkte zählen",
    text: "Lege deinen Standort und Radius fest und markiere die Filialen, die für deinen Alltag wirklich infrage kommen.",
    icon: MapPinned,
  },
  {
    eyebrow: "Favoriten im Blick",
    title: "Lieblingsprodukte nicht mehr verpassen",
    text: "Speichere Produkte als Favoriten. LocalPrices zeigt dir passende Angebote und später auch sinnvolle Alternativen derselben Produktart.",
    icon: Heart,
  },
  {
    eyebrow: "Clever einkaufen",
    title: "Aus deiner Liste wird ein Sparplan",
    text: "Fülle deine Einkaufsliste und vergleiche Preise, Märkte und Fahrtkosten. So findest du die Kombination, die am besten zu deinem Einkauf passt.",
    icon: ListChecks,
  },
];

function onboardingAlreadyCompleted(): boolean {
  if (typeof window === "undefined") return true;
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function rememberCompletion(): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, "1");
  } catch {
    // Some Safari/privacy contexts can deny localStorage. The flow still closes
    // for the current page session; the device cookie remains unaffected.
  }
}

export function FirstStartOnboarding() {
  const [ready, setReady] = useState(false);
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);
  const pointerStartX = useRef<number | null>(null);

  useEffect(() => {
    const completed = onboardingAlreadyCompleted();
    setOpen(!completed);
    setReady(true);
  }, []);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  if (!ready || !open) return null;

  const card = CARDS[step];
  const Icon = card.icon;
  const lastStep = step === CARDS.length - 1;

  const complete = () => {
    rememberCompletion();
    setOpen(false);
  };

  const next = () => {
    if (lastStep) {
      complete();
      return;
    }
    setStep((current) => Math.min(current + 1, CARDS.length - 1));
  };

  const previous = () => {
    setStep((current) => Math.max(current - 1, 0));
  };

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    pointerStartX.current = event.clientX;
  };

  const handlePointerUp = (event: PointerEvent<HTMLDivElement>) => {
    if (pointerStartX.current === null) return;
    const deltaX = event.clientX - pointerStartX.current;
    pointerStartX.current = null;

    if (deltaX <= -SWIPE_THRESHOLD_PX) next();
    if (deltaX >= SWIPE_THRESHOLD_PX && step > 0) previous();
  };

  return (
    <div
      className="fixed inset-0 z-[100] flex justify-center bg-background"
      role="dialog"
      aria-modal="true"
      aria-label="Einführung in LocalPrices"
    >
      <div className="flex min-h-[100dvh] w-full max-w-[460px] flex-col overflow-hidden bg-background px-5 pb-[max(1.25rem,env(safe-area-inset-bottom))] pt-[max(1.25rem,env(safe-area-inset-top))]">
        <div className="flex items-center justify-between">
          <div className="font-display text-lg font-semibold tracking-tight text-primary">
            LocalPrices
          </div>
          <button
            type="button"
            onClick={complete}
            className="rounded-full px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            Überspringen
          </button>
        </div>

        <div
          className="flex flex-1 touch-pan-y select-none flex-col justify-center py-6"
          onPointerDown={handlePointerDown}
          onPointerUp={handlePointerUp}
          onPointerCancel={() => {
            pointerStartX.current = null;
          }}
        >
          <div className="mx-auto flex w-full max-w-sm flex-col items-center text-center">
            <div className="mb-8 flex h-28 w-28 items-center justify-center rounded-[2rem] bg-primary/10 shadow-sm ring-1 ring-primary/10">
              <Icon className="h-14 w-14 text-primary" strokeWidth={1.75} aria-hidden="true" />
            </div>

            <p className="text-sm font-semibold uppercase tracking-[0.12em] text-primary">
              {card.eyebrow}
            </p>
            <h1 className="mt-3 font-display text-3xl font-semibold leading-tight tracking-tight text-foreground">
              {card.title}
            </h1>
            <p className="mt-4 max-w-[34ch] text-base leading-7 text-muted-foreground">
              {card.text}
            </p>

            <p className="mt-7 text-xs text-muted-foreground/80">
              Wische nach links oder nutze „Weiter“.
            </p>
          </div>
        </div>

        <div className="space-y-5">
          <div className="flex justify-center gap-2" aria-label={`Schritt ${step + 1} von ${CARDS.length}`}>
            {CARDS.map((item, index) => (
              <button
                key={item.title}
                type="button"
                aria-label={`Zu Schritt ${index + 1}`}
                aria-current={index === step ? "step" : undefined}
                onClick={() => setStep(index)}
                className={`h-2 rounded-full transition-all ${
                  index === step ? "w-7 bg-primary" : "w-2 bg-border"
                }`}
              />
            ))}
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={previous}
              disabled={step === 0}
              className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border border-border bg-surface text-foreground transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-0"
              aria-label="Zurück"
            >
              <ArrowLeft className="h-5 w-5" />
            </button>

            <button
              type="button"
              onClick={next}
              className="flex h-12 flex-1 items-center justify-center gap-2 rounded-2xl bg-primary px-5 font-semibold text-primary-foreground shadow-sm transition-transform active:scale-[0.99]"
            >
              {lastStep ? "Los geht's" : "Weiter"}
              <ArrowRight className="h-5 w-5" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

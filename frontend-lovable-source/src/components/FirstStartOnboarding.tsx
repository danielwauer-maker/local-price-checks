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
import { createPortal } from "react-dom";

import { apiFetch } from "@/lib/api-client";

const STORAGE_KEY = "lp_onboarding_v2_completed";
const SWIPE_THRESHOLD_PX = 56;
const PROFILE_STEP = 1;

type OnboardingCard = {
  eyebrow: string;
  title: string;
  text: string;
  icon: LucideIcon;
};

type ProfileDraft = {
  displayName: string;
  postalCode: string;
  city: string;
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
    title: "Richte LocalPrices für deine Umgebung ein",
    text: "Vorname, PLZ und Ort helfen uns, passende Filialen in deiner Nähe zu zeigen. Alles ist optional und später änderbar.",
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

function hasProfileInput(profile: ProfileDraft): boolean {
  return Boolean(profile.displayName.trim() || profile.postalCode.trim() || profile.city.trim());
}

export function FirstStartOnboarding() {
  const [ready, setReady] = useState(false);
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);
  const [profile, setProfile] = useState<ProfileDraft>({ displayName: "", postalCode: "", city: "" });
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileError, setProfileError] = useState("");
  const pointerStartX = useRef<number | null>(null);

  useEffect(() => {
    const completed = onboardingAlreadyCompleted();
    setOpen(!completed);
    setReady(true);
  }, []);

  useEffect(() => {
    if (!open) return;

    let cancelled = false;
    void apiFetch("/api/ux/bootstrap")
      .then(async (response) => {
        if (!response.ok) return;
        const data = await response.json();
        if (cancelled) return;
        const current = data?.profile;
        setProfile({
          displayName: current?.displayName === "Local User" ? "" : current?.displayName || "",
          postalCode: current?.postalCode || "",
          city: current?.city || "",
        });
      })
      .catch(() => undefined);

    return () => {
      cancelled = true;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  if (!ready || !open || typeof document === "undefined") return null;

  const card = CARDS[step];
  const Icon = card.icon;
  const lastStep = step === CARDS.length - 1;
  const profileStep = step === PROFILE_STEP;

  const complete = () => {
    rememberCompletion();
    setOpen(false);
  };

  const advance = () => {
    if (lastStep) {
      complete();
      return;
    }
    setStep((current) => Math.min(current + 1, CARDS.length - 1));
  };

  const saveProfileAndAdvance = async () => {
    if (!hasProfileInput(profile)) {
      advance();
      return;
    }

    setSavingProfile(true);
    setProfileError("");
    try {
      const response = await apiFetch("/api/ux/profile", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          display_name: profile.displayName,
          postal_code: profile.postalCode,
          city: profile.city,
        }),
      });
      if (!response.ok) throw new Error("profile update failed");
      advance();
    } catch {
      setProfileError("Die Angaben konnten gerade nicht gespeichert werden. Du kannst sie überspringen und später nachtragen.");
    } finally {
      setSavingProfile(false);
    }
  };

  const next = () => {
    if (profileStep) {
      void saveProfileAndAdvance();
      return;
    }
    advance();
  };

  const previous = () => {
    setProfileError("");
    setStep((current) => Math.max(current - 1, 0));
  };

  const skipProfile = () => {
    setProfileError("");
    advance();
  };

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (target.closest("input, button")) return;
    pointerStartX.current = event.clientX;
  };

  const handlePointerUp = (event: PointerEvent<HTMLDivElement>) => {
    if (pointerStartX.current === null) return;
    const deltaX = event.clientX - pointerStartX.current;
    pointerStartX.current = null;

    if (deltaX <= -SWIPE_THRESHOLD_PX) next();
    if (deltaX >= SWIPE_THRESHOLD_PX && step > 0) previous();
  };

  const overlay = (
    <div
      className="fixed inset-0 isolate flex justify-center bg-background"
      style={{ zIndex: 2147483647 }}
      role="dialog"
      aria-modal="true"
      aria-label="Einführung in LocalPrices"
    >
      <div className="flex min-h-[100dvh] w-full max-w-[460px] flex-col overflow-hidden bg-background px-5 pb-[max(1.25rem,env(safe-area-inset-bottom))] pt-[max(1.25rem,env(safe-area-inset-top))]">
        <div className="flex items-center justify-between">
          <div className="font-display text-lg font-semibold tracking-tight text-primary">LocalPrices</div>
          <button
            type="button"
            onClick={complete}
            className="rounded-full px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            Überspringen
          </button>
        </div>

        <div
          className="flex flex-1 touch-pan-y select-none flex-col justify-center py-5"
          onPointerDown={handlePointerDown}
          onPointerUp={handlePointerUp}
          onPointerCancel={() => {
            pointerStartX.current = null;
          }}
        >
          <div className="mx-auto flex w-full max-w-sm flex-col items-center text-center">
            <div className={`flex items-center justify-center rounded-[2rem] bg-primary/10 shadow-sm ring-1 ring-primary/10 ${profileStep ? "mb-4 h-20 w-20" : "mb-8 h-28 w-28"}`}>
              <Icon className={profileStep ? "h-10 w-10 text-primary" : "h-14 w-14 text-primary"} strokeWidth={1.75} aria-hidden="true" />
            </div>

            <p className="text-sm font-semibold uppercase tracking-[0.12em] text-primary">{card.eyebrow}</p>
            <h1 className={`${profileStep ? "mt-2 text-2xl" : "mt-3 text-3xl"} font-display font-semibold leading-tight tracking-tight text-foreground`}>
              {card.title}
            </h1>
            <p className={`${profileStep ? "mt-2" : "mt-4"} max-w-[34ch] text-base leading-7 text-muted-foreground`}>
              {card.text}
            </p>

            {profileStep ? (
              <div className="mt-5 w-full max-w-xs space-y-3 text-left">
                <label className="block">
                  <span className="mb-1.5 block text-xs font-semibold text-foreground">Vorname</span>
                  <input
                    value={profile.displayName}
                    onChange={(event) => setProfile((current) => ({ ...current, displayName: event.target.value }))}
                    autoComplete="given-name"
                    maxLength={80}
                    placeholder="z. B. Daniel"
                    className="h-11 w-full rounded-xl border border-border bg-surface px-3 text-base text-foreground outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/15"
                  />
                </label>
                <div className="grid grid-cols-[0.85fr_1.4fr] gap-2.5">
                  <label className="block">
                    <span className="mb-1.5 block text-xs font-semibold text-foreground">PLZ</span>
                    <input
                      value={profile.postalCode}
                      onChange={(event) => setProfile((current) => ({ ...current, postalCode: event.target.value.replace(/[^0-9]/g, "").slice(0, 5) }))}
                      inputMode="numeric"
                      autoComplete="postal-code"
                      placeholder="576..."
                      className="h-11 w-full rounded-xl border border-border bg-surface px-3 text-base text-foreground outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/15"
                    />
                  </label>
                  <label className="block">
                    <span className="mb-1.5 block text-xs font-semibold text-foreground">Ort</span>
                    <input
                      value={profile.city}
                      onChange={(event) => setProfile((current) => ({ ...current, city: event.target.value }))}
                      autoComplete="address-level2"
                      maxLength={100}
                      placeholder="Dein Ort"
                      className="h-11 w-full rounded-xl border border-border bg-surface px-3 text-base text-foreground outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/15"
                    />
                  </label>
                </div>
                {profileError && <p className="text-xs leading-5 text-destructive">{profileError}</p>}
                <button
                  type="button"
                  onClick={skipProfile}
                  className="mx-auto block rounded-lg px-2 py-1 text-xs font-medium text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
                >
                  Später einrichten
                </button>
              </div>
            ) : (
              <p className="mt-7 text-xs text-muted-foreground/80">Wische nach links oder nutze „Weiter“.</p>
            )}
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
                onClick={() => {
                  setProfileError("");
                  setStep(index);
                }}
                className={`h-2 rounded-full transition-all ${index === step ? "w-7 bg-primary" : "w-2 bg-border"}`}
              />
            ))}
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={previous}
              disabled={step === 0 || savingProfile}
              className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border border-border bg-surface text-foreground transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-0"
              aria-label="Zurück"
            >
              <ArrowLeft className="h-5 w-5" />
            </button>

            <button
              type="button"
              onClick={next}
              disabled={savingProfile}
              className="flex h-12 flex-1 items-center justify-center gap-2 rounded-2xl bg-primary px-5 font-semibold text-primary-foreground shadow-sm transition-transform active:scale-[0.99] disabled:opacity-70"
            >
              {savingProfile ? "Speichere …" : profileStep && hasProfileInput(profile) ? "Speichern & weiter" : lastStep ? "Los geht's" : "Weiter"}
              {!savingProfile && <ArrowRight className="h-5 w-5" />}
            </button>
          </div>
        </div>
      </div>
    </div>
  );

  return createPortal(overlay, document.body);
}

import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useState, type ReactNode } from "react";
import {
  Bell,
  BookOpen,
  Car,
  ChevronRight,
  Download,
  Info,
  LogIn,
  LogOut,
  MapPin,
  Navigation,
  ShieldCheck,
  Sparkles,
  User,
} from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/AppShell";
import { SPARENO_ONBOARDING_REPLAY_EVENT } from "@/components/FirstStartOnboarding";
import { ReviewerSettings } from "@/components/lokero/ReviewerSettings";
import { useStore } from "@/lib/app-store";
import { supabase } from "@/integrations/supabase/client";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/einstellungen")({
  head: () => ({
    meta: [
      { title: "Einstellungen – Spareno" },
      {
        name: "description",
        content: "Standort, Suchradius, Fahrtkosten, Benachrichtigungen und Account in Spareno anpassen.",
      },
      { property: "og:title", content: "Einstellungen – Spareno" },
      {
        property: "og:description",
        content: "Standort, Radius, Fahrtkosten und Benachrichtigungen anpassen.",
      },
    ],
  }),
  component: SettingsPage,
});

function Section({ icon: Icon, title, children }: { icon: typeof MapPin; title: string; children: ReactNode }) {
  return (
    <section className="card-surface overflow-hidden">
      <h2 className="flex items-center gap-2 border-b border-border px-3.5 py-2.5 text-[13px] font-semibold text-navy">
        <Icon className="h-4 w-4 shrink-0 text-primary" strokeWidth={2} />
        {title}
      </h2>
      <div className="space-y-3 p-3.5">{children}</div>
    </section>
  );
}

function Row({ label, hint, action }: { label: string; hint?: string; action: ReactNode }) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3">
      <div className="min-w-0">
        <p className="truncate text-[13px] font-medium text-navy">{label}</p>
        {hint && <p className="truncate text-[11px] text-muted-foreground">{hint}</p>}
      </div>
      {action}
    </div>
  );
}

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative h-6 w-11 shrink-0 overflow-hidden rounded-full border transition-colors duration-200",
        checked ? "border-primary bg-primary" : "border-border bg-muted-surface",
      )}
    >
      <span
        className={cn(
          "absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-surface shadow-sm transition-transform duration-200",
          checked ? "translate-x-5" : "translate-x-0",
        )}
      />
    </button>
  );
}

function SettingsPage() {
  const store = useStore();
  const navigate = useNavigate();
  const [accountEmail, setAccountEmail] = useState<string | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [installed] = useState(
    () => typeof window !== "undefined" && window.matchMedia("(display-mode: standalone)").matches,
  );

  useEffect(() => {
    let active = true;
    void supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      setAccountEmail(data.session?.user.email ?? null);
      setAuthReady(true);
    });

    const { data: subscription } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!active) return;
      setAccountEmail(session?.user.email ?? null);
      setAuthReady(true);
    });

    return () => {
      active = false;
      subscription.subscription.unsubscribe();
    };
  }, []);

  async function signOut() {
    await supabase.auth.signOut();
    toast.success("Abgemeldet");
    navigate({ to: "/auth" });
  }

  function replayOnboarding() {
    window.dispatchEvent(new Event(SPARENO_ONBOARDING_REPLAY_EVENT));
  }

  return (
    <div className="pb-4">
      <PageHeader title="Einstellungen" subtitle="Spareno an deinen Einkauf anpassen" />

      <div className="space-y-3 px-4 pt-1">
        <Section icon={MapPin} title="Standort">
          <Row label="Aktueller Standort" hint={store.location.label} action={<span />} />
          <div className="flex gap-2">
            <Link to="/regionen" className="tap-target flex h-10 flex-1 items-center justify-center rounded-xl border border-border bg-surface text-[13px] font-semibold text-navy">
              Standort ändern
            </Link>
            <button
              type="button"
              onClick={() => navigator.geolocation?.getCurrentPosition(
                (pos) => store.setLocation({ lat: pos.coords.latitude, lng: pos.coords.longitude, label: "Mein Standort" }),
                () => toast.error("Standortfreigabe wurde abgelehnt"),
              )}
              className="tap-target flex h-10 flex-1 items-center justify-center gap-1.5 rounded-xl bg-primary text-[13px] font-semibold text-primary-foreground"
            >
              <Navigation className="h-4 w-4" /> Standort freigeben
            </button>
          </div>
        </Section>

        <Section icon={Navigation} title="Suchradius">
          <div className="flex flex-wrap gap-2">
            {[5, 10, 15, 20, 25].map((km) => (
              <button
                key={km}
                type="button"
                onClick={() => store.setRadius(km)}
                aria-pressed={store.radius === km}
                className={cn(
                  "h-9 rounded-full border px-3.5 text-[13px] font-medium transition-colors duration-150",
                  store.radius === km ? "border-primary bg-primary text-primary-foreground" : "border-border bg-surface text-muted-foreground",
                )}
              >
                {km} km
              </button>
            ))}
          </div>
        </Section>

        <Section icon={Car} title="Fahrtkosten">
          <Row
            label="Kosten pro Kilometer"
            hint="Wird erst mit der Einkaufsoptimierung verwendet"
            action={
              <label className="flex items-center gap-1 rounded-lg bg-muted-surface px-2 py-1">
                <span className="sr-only">Kosten pro Kilometer in Euro</span>
                <input
                  type="number"
                  min={0}
                  step={0.05}
                  value={store.travelCostPerKm}
                  onChange={(e) => store.setTravelCostPerKm(Number(e.target.value))}
                  className="tabular w-16 bg-transparent text-right text-[13px] font-semibold text-navy outline-none"
                />
                <span className="text-[12px] text-muted-foreground">€/km</span>
              </label>
            }
          />
        </Section>

        <Section icon={Bell} title="Benachrichtigungen">
          {([
            ["priceAlerts", "Preisalarme"],
            ["newOffers", "Neue Angebote"],
            ["regionAvailable", "Region verfügbar"],
            ["favoriteOffers", "Favoriten im Angebot"],
          ] as const).map(([key, label]) => (
            <Row
              key={key}
              label={label}
              action={<Toggle checked={store.notifications[key]} onChange={(v) => store.setNotification(key, v)} label={label} />}
            />
          ))}
        </Section>

        <Section icon={ShieldCheck} title="Datenschutz">
          <Row label="Datenschutzerklärung" hint="Wie wir Daten verarbeiten" action={<span />} />
          <Row label="Standortdaten" hint="Nur zur Umkreissuche verwendet" action={<span />} />
          <Row label="Tracking" hint="Anonyme Nutzungsstatistik" action={<Toggle checked={false} onChange={() => {}} label="Tracking" />} />
        </Section>

        <Section icon={User} title="Account">
          {!authReady ? (
            <div className="h-16 animate-pulse rounded-xl bg-muted-surface" />
          ) : accountEmail ? (
            <>
              <Row
                label="Angemeldet als"
                hint={accountEmail}
                action={<span className="rounded-full bg-primary-soft px-2 py-1 text-[10px] font-semibold text-primary-deep">Registriert</span>}
              />
              <Row label="Spareno Premium" hint="Erweiterte Optimierung" action={<Sparkles className="h-4 w-4 text-primary" />} />
              <button
                type="button"
                onClick={signOut}
                className="tap-target flex h-11 w-full items-center justify-center gap-2 rounded-xl border border-destructive/25 bg-destructive/5 text-[13px] font-semibold text-destructive transition-colors hover:bg-destructive/10 active:bg-destructive/15"
              >
                <LogOut className="h-4 w-4" /> Abmelden
              </button>
            </>
          ) : (
            <>
              <Row label="Noch nicht angemeldet" hint="Mit Konto kannst du deine Daten geräteübergreifend nutzen." action={<span />} />
              <Link to="/auth" className="tap-target flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-primary text-[13px] font-semibold text-primary-foreground">
                <LogIn className="h-4 w-4" /> Anmelden oder registrieren
              </Link>
            </>
          )}
        </Section>

        <Section icon={Download} title="App">
          <Row label="Installationsstatus" hint={installed ? "Als App installiert" : "Im Browser geöffnet"} action={<span />} />
          <button
            type="button"
            onClick={replayOnboarding}
            className="tap-target group flex min-h-14 w-full items-center gap-3 rounded-xl bg-primary/[0.035] px-2.5 py-2 text-left transition-colors hover:bg-primary/[0.065] active:bg-primary/[0.08]"
          >
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-primary-soft text-primary">
              <BookOpen className="h-4 w-4" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-[13px] font-semibold text-navy">Einführung</span>
              <span className="mt-0.5 block text-[11px] text-muted-foreground">Die 4 Spareno-Karten erneut ansehen</span>
            </span>
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
          </button>
          <ReviewerSettings />
          <Row label="Über Spareno" hint="Besser einkaufen." action={<Info className="h-4 w-4 text-muted-foreground" />} />
        </Section>
      </div>
    </div>
  );
}

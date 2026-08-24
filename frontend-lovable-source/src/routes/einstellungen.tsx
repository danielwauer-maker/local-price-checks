import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useState, type ReactNode } from "react";
import {
  Bell,
  Car,
  Download,
  Info,
  LogOut,
  MapPin,
  Navigation,
  Salad,
  ShieldCheck,
  Sparkles,
  Store,
  User,
} from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/AppShell";
import { MarketLogo } from "@/components/lokero/MarketLogo";
import { ReviewerSettings } from "@/components/lokero/ReviewerSettings";
import { RETAILER_OPTIONS, type Chain, type DietTag } from "@/data/lokero";
import { useStore } from "@/lib/app-store";
import { supabase } from "@/integrations/supabase/client";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/einstellungen")({
  head: () => ({
    meta: [
      { title: "Einstellungen – Lokero" },
      {
        name: "description",
        content:
          "Standort, Suchradius, bevorzugte Märkte, Fahrtkosten, Benachrichtigungen und Ernährungsfilter in Lokero anpassen.",
      },
      { property: "og:title", content: "Einstellungen – Lokero" },
      {
        property: "og:description",
        content: "Standort, Radius, Märkte, Fahrtkosten und Benachrichtigungen anpassen.",
      },
    ],
  }),
  component: SettingsPage,
});

function Section({
  icon: Icon,
  title,
  children,
}: {
  icon: typeof MapPin;
  title: string;
  children: ReactNode;
}) {
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

function Row({
  label,
  hint,
  action,
}: {
  label: string;
  hint?: string;
  action: ReactNode;
}) {
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

function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative h-6 w-11 shrink-0 rounded-full transition-colors duration-200",
        checked ? "bg-primary" : "bg-muted-surface border border-border",
      )}
    >
      <span
        className={cn(
          "absolute top-0.5 h-5 w-5 rounded-full bg-surface shadow-sm transition-transform duration-200",
          checked ? "translate-x-[22px]" : "translate-x-0.5",
        )}
      />
    </button>
  );
}

const DIETS: Array<{ id: DietTag; label: string }> = [
  { id: "vegan", label: "Vegan" },
  { id: "vegetarisch", label: "Vegetarisch" },
  { id: "glutenfrei", label: "Glutenfrei" },
  { id: "bio", label: "Bio" },
];

function SettingsPage() {
  const store = useStore();
  const navigate = useNavigate();
  const [installed] = useState(
    () => typeof window !== "undefined" && window.matchMedia("(display-mode: standalone)").matches,
  );

  async function signOut() {
    await supabase.auth.signOut();
    toast.success("Abgemeldet");
    navigate({ to: "/auth" });
  }

  return (
    <div className="pb-4">
      <PageHeader title="Einstellungen" subtitle="Lokero an deinen Einkauf anpassen" />

      <div className="space-y-3 px-4 pt-1">
        <Section icon={MapPin} title="Standort">
          <Row label="Aktueller Standort" hint={store.location.label} action={<span />} />
          <div className="flex gap-2">
            <Link
              to="/regionen"
              className="tap-target flex h-10 flex-1 items-center justify-center rounded-xl border border-border bg-surface text-[13px] font-semibold text-navy"
            >
              Standort ändern
            </Link>
            <button
              type="button"
              onClick={() =>
                navigator.geolocation?.getCurrentPosition(
                  (pos) =>
                    store.setLocation({
                      lat: pos.coords.latitude,
                      lng: pos.coords.longitude,
                      label: "Mein Standort",
                    }),
                  () => toast.error("Standortfreigabe wurde abgelehnt"),
                )
              }
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
                  store.radius === km
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border bg-surface text-muted-foreground",
                )}
              >
                {km} km
              </button>
            ))}
          </div>
        </Section>

        <Section icon={Store} title="Bevorzugte Märkte">
          <ul className="space-y-2">
            {RETAILER_OPTIONS.map((chain) => {
              const active = store.preferredChains.includes(chain);
              const known = ["REWE", "Lidl", "ALDI SÜD", "Netto", "EDEKA"].includes(chain);
              return (
                <li key={chain} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3">
                  <span className="flex min-w-0 items-center gap-2">
                    {known && <MarketLogo chain={chain as Chain} size="xs" />}
                    <span className="truncate text-[13px] font-medium text-navy">{chain}</span>
                  </span>
                  <Toggle
                    checked={active}
                    onChange={() => store.togglePreferredChain(chain)}
                    label={`${chain} bevorzugen`}
                  />
                </li>
              );
            })}
          </ul>
        </Section>

        <Section icon={Car} title="Fahrtkosten">
          <Row
            label="Kosten pro Kilometer"
            hint="Fließt in die Einkaufsoptimierung ein"
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
          {(
            [
              ["priceAlerts", "Preisalarme"],
              ["newOffers", "Neue Angebote"],
              ["regionAvailable", "Region verfügbar"],
              ["favoriteOffers", "Favoriten im Angebot"],
            ] as const
          ).map(([key, label]) => (
            <Row
              key={key}
              label={label}
              action={
                <Toggle
                  checked={store.notifications[key]}
                  onChange={(v) => store.setNotification(key, v)}
                  label={label}
                />
              }
            />
          ))}
        </Section>

        <Section icon={Salad} title="Ernährungsfilter">
          <div className="flex flex-wrap gap-2">
            {DIETS.map((d) => {
              const active = store.diet.includes(d.id);
              return (
                <button
                  key={d.id}
                  type="button"
                  onClick={() => store.toggleDiet(d.id)}
                  aria-pressed={active}
                  className={cn(
                    "h-9 rounded-full border px-3.5 text-[13px] font-medium transition-colors duration-150",
                    active
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border bg-surface text-muted-foreground",
                  )}
                >
                  {d.label}
                </button>
              );
            })}
          </div>
        </Section>

        <Section icon={ShieldCheck} title="Datenschutz">
          <Row label="Datenschutzerklärung" hint="Wie wir Daten verarbeiten" action={<span />} />
          <Row label="Standortdaten" hint="Nur zur Umkreissuche verwendet" action={<span />} />
          <Row
            label="Tracking"
            hint="Anonyme Nutzungsstatistik"
            action={<Toggle checked={false} onChange={() => {}} label="Tracking" />}
          />
        </Section>

        <Section icon={User} title="Account">
          <Row label="Profil" hint="Anmeldung & Konto" action={<span />} />
          <Row
            label="Lokero Premium"
            hint="Erweiterte Optimierung"
            action={<Sparkles className="h-4 w-4 text-primary" />}
          />
          <button
            type="button"
            onClick={signOut}
            className="tap-target flex h-11 w-full items-center justify-center gap-2 rounded-xl border border-border bg-surface text-[13px] font-semibold text-navy"
          >
            <LogOut className="h-4 w-4" /> Abmelden
          </button>
        </Section>

        <Section icon={Download} title="App">
          <Row
            label="Installationsstatus"
            hint={installed ? "Als App installiert" : "Im Browser geöffnet"}
            action={<span />}
          />
          <ReviewerSettings />
          <Row
            label="Über Lokero"
            hint="Alles in deiner Nähe. Das Beste für dich."
            action={<Info className="h-4 w-4 text-muted-foreground" />}
          />
        </Section>
      </div>
    </div>
  );
}

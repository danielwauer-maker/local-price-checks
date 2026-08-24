import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { BookOpen, MapPin, Save, UserRound } from "lucide-react";
import { PageHeader } from "@/components/AppShell";
import { useStore } from "@/lib/app-store";
import { toast } from "sonner";

export const Route = createFileRoute("/settings")({ component: SettingsPage });

const ONBOARDING_KEY = "lp_onboarding_v2_completed";

function SettingsPage() {
  const { profile, radius, setRadius, updateProfile, hydrated } = useStore();
  const [displayName, setDisplayName] = useState(profile.displayName);
  const [postalCode, setPostalCode] = useState(profile.postalCode);
  const [city, setCity] = useState(profile.city);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!hydrated) return;
    setDisplayName(profile.displayName);
    setPostalCode(profile.postalCode);
    setCity(profile.city);
  }, [hydrated, profile.displayName, profile.postalCode, profile.city]);

  async function save() {
    setSaving(true);
    try {
      await updateProfile({ displayName, postalCode, city });
      toast.success("Einstellungen gespeichert");
    } catch {
      toast.error("Einstellungen konnten nicht gespeichert werden");
    } finally {
      setSaving(false);
    }
  }

  function replayOnboarding() {
    try {
      window.localStorage.removeItem(ONBOARDING_KEY);
    } catch {
      // Reload still gives the user another chance in browsers with storage restrictions.
    }
    window.location.assign("/");
  }

  return (
    <div>
      <PageHeader title="Einstellungen" subtitle="Persönliche Angaben und Standort" />
      <section className="space-y-4 px-5">
        <div className="surface-card p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold"><UserRound className="h-4 w-4 text-primary" /> Name</div>
          <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="Dein Name" className="w-full rounded-xl border border-border bg-background px-3 py-2.5 text-sm outline-none focus:border-primary" />
        </div>

        <div className="surface-card p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold"><MapPin className="h-4 w-4 text-primary" /> Standort</div>
          <div className="grid grid-cols-[110px_1fr] gap-2">
            <input value={postalCode} onChange={(e) => setPostalCode(e.target.value)} placeholder="PLZ" inputMode="numeric" className="rounded-xl border border-border bg-background px-3 py-2.5 text-sm outline-none focus:border-primary" />
            <input value={city} onChange={(e) => setCity(e.target.value)} placeholder="Ort" className="rounded-xl border border-border bg-background px-3 py-2.5 text-sm outline-none focus:border-primary" />
          </div>
          <p className="mt-2 text-[11px] text-muted-foreground">Nach dem Speichern wird der Standort für Karte, Radius und Fahrtkosten neu gesetzt.</p>
        </div>

        <div className="surface-card p-4">
          <div className="flex items-center justify-between text-sm font-semibold"><span>Suchradius</span><span className="text-primary">{radius} km</span></div>
          <input type="range" min={2} max={25} value={radius} onChange={(e) => setRadius(Number(e.target.value))} className="mt-3 h-1.5 w-full cursor-pointer appearance-none rounded-full bg-secondary accent-primary" />
        </div>

        <div className="surface-card p-4">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold"><BookOpen className="h-4 w-4 text-primary" /> Einführung</div>
          <p className="mb-3 text-xs leading-5 text-muted-foreground">Die vier Einführungskarten mit Märkten, Favoriten und Sparplan jederzeit noch einmal ansehen.</p>
          <button type="button" onClick={replayOnboarding} className="w-full rounded-xl border border-primary/20 bg-primary/5 px-3 py-2.5 text-sm font-semibold text-primary hover:bg-primary/10">
            Einführung erneut ansehen
          </button>
        </div>

        <button onClick={save} disabled={saving} className="flex w-full items-center justify-center gap-2 rounded-2xl bg-primary px-4 py-3 text-sm font-semibold text-primary-foreground shadow-float disabled:opacity-60">
          <Save className="h-4 w-4" /> {saving ? "Speichert…" : "Speichern"}
        </button>
      </section>
    </div>
  );
}

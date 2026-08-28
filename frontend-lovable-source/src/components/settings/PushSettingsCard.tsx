import { useEffect, useState } from "react";
import { BellRing, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { disablePushNotifications, enablePushNotifications, fetchPushConfig, pushSupported } from "@/services/push-api";

export function PushSettingsCard() {
  const [loading, setLoading] = useState(true);
  const [enabled, setEnabled] = useState(false);
  const [linked, setLinked] = useState(false);
  const [supported, setSupported] = useState(false);
  const [supportChecked, setSupportChecked] = useState(false);

  useEffect(() => {
    const currentSupport = pushSupported();
    setSupported(currentSupport);
    setSupportChecked(true);
    if (!currentSupport) {
      setLoading(false);
      return;
    }

    let active = true;
    void fetchPushConfig()
      .then((config) => {
        if (!active) return;
        setEnabled(config.enabledOnThisDevice && Notification.permission === "granted");
        setLinked(config.linked);
      })
      .catch(() => {})
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const toggle = async () => {
    if (loading) return;
    setLoading(true);
    try {
      if (enabled) {
        await disablePushNotifications();
        setEnabled(false);
        toast.success("Push-Benachrichtigungen auf diesem Gerät deaktiviert");
      } else {
        await enablePushNotifications();
        setEnabled(true);
        toast.success("Push-Benachrichtigungen auf diesem Gerät aktiviert");
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Push konnte nicht geändert werden");
    } finally {
      setLoading(false);
    }
  };

  if (!supportChecked) {
    return (
      <div className="rounded-xl border border-border bg-muted-surface/35 p-3" aria-label="Push-Status wird geprüft">
        <div className="flex items-center gap-3">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-primary-soft text-primary"><BellRing className="h-4 w-4" /></span>
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-semibold text-navy">Push auf diesem Gerät</p>
            <p className="mt-0.5 text-[11px] text-muted-foreground">Unterstützung wird geprüft …</p>
          </div>
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden="true" />
        </div>
      </div>
    );
  }

  if (!supported) {
    return (
      <div className="rounded-xl border border-border bg-muted-surface/55 p-3 text-[11px] leading-relaxed text-muted-foreground">
        Push wird von diesem Browser aktuell nicht unterstützt. Auf iPhone funktioniert Web Push ab iOS 16.4 in der zum Home-Bildschirm hinzugefügten Spareno-App.
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border bg-muted-surface/35 p-3">
      <div className="flex items-start gap-3">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-primary-soft text-primary"><BellRing className="h-4 w-4" /></span>
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-semibold text-navy">Push auf diesem Gerät</p>
          <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
            Für gemeinsame Einkaufslisten fasst Spareno schnelle Änderungen intelligent zusammen, z. B. „3 Artikel wurden erledigt“.
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          disabled={loading || !linked}
          onClick={() => void toggle()}
          className={`relative h-7 w-12 shrink-0 rounded-full border transition-colors ${enabled ? "border-primary bg-primary" : "border-border bg-surface"} ${loading || !linked ? "opacity-50" : ""}`}
          aria-label="Push-Benachrichtigungen auf diesem Gerät"
        >
          {loading ? <Loader2 className="absolute left-3.5 top-1.5 h-3.5 w-3.5 animate-spin text-muted-foreground" /> : <span className={`absolute top-0.5 h-5.5 w-5.5 rounded-full bg-white shadow transition-transform ${enabled ? "translate-x-5.5" : "translate-x-0.5"}`} />}
        </button>
      </div>
      {!linked && <p className="mt-2 text-[10px] text-muted-foreground">Melde dich an, um Push gerätebezogen zu aktivieren.</p>}
    </div>
  );
}

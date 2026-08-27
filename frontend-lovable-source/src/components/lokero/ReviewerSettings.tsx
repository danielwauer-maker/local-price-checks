import { Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { LockKeyhole, ShieldCheck, Wrench } from "lucide-react";
import { toast } from "sonner";
import {
  fetchReviewerStatus,
  lockReviewer,
  unlockReviewer,
  type ReviewerStatus,
} from "@/services/lokero-api";

export function ReviewerSettings() {
  const [status, setStatus] = useState<ReviewerStatus>({ reviewer: false });
  const [unlockVisible, setUnlockVisible] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const taps = useRef<number[]>([]);

  useEffect(() => {
    void fetchReviewerStatus().then(setStatus);
  }, []);

  function versionTap() {
    const now = Date.now();
    taps.current = [...taps.current.filter((t) => now - t < 3500), now];
    if (taps.current.length >= 7) {
      taps.current = [];
      setUnlockVisible(true);
      toast.message("Interner Prüfmodus", { description: "Administrator-Anmeldung erforderlich." });
    }
  }

  async function unlock(e: React.FormEvent) {
    e.preventDefault();
    if (!username || !password) return;
    setBusy(true);
    try {
      const result = await unlockReviewer(username, password);
      setStatus(result);
      setPassword("");
      setUnlockVisible(false);
      toast.success("Prüfmodus für dieses Gerät freigeschaltet");
    } catch {
      toast.error("Prüfmodus konnte nicht freigeschaltet werden");
    } finally {
      setBusy(false);
    }
  }

  async function lock() {
    setBusy(true);
    try {
      await lockReviewer();
      setStatus({ reviewer: false });
      toast.success("Prüfmodus deaktiviert");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={versionTap}
        className="grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-3 text-left"
        aria-label="Spareno Version 1.0.0"
      >
        <span className="min-w-0">
          <span className="block text-[13px] font-medium text-navy">Version</span>
          <span className="block text-[11px] text-muted-foreground">1.0.0 (Design Freeze)</span>
        </span>
        <span className="text-[11px] font-medium text-muted-foreground">Spareno</span>
      </button>

      {unlockVisible && !status.reviewer && (
        <form onSubmit={unlock} className="rounded-xl border border-border bg-muted-surface p-3">
          <div className="mb-2 flex items-center gap-2 text-[12px] font-semibold text-navy">
            <LockKeyhole className="h-4 w-4 text-primary" /> Prüfmodus freischalten
          </div>
          <p className="mb-2 text-[11px] text-muted-foreground">
            Zugangsdaten werden nur zur einmaligen Freischaltung dieses Geräts verwendet und nicht gespeichert.
          </p>
          <div className="space-y-2">
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              placeholder="Admin-Benutzer"
              className="h-10 w-full rounded-xl border border-border bg-surface px-3 text-[13px] outline-none"
            />
            <input
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              type="password"
              autoComplete="current-password"
              placeholder="Passwort"
              className="h-10 w-full rounded-xl border border-border bg-surface px-3 text-[13px] outline-none"
            />
            <button
              type="submit"
              disabled={busy}
              className="h-10 w-full rounded-xl bg-primary text-[13px] font-semibold text-primary-foreground disabled:opacity-60"
            >
              Dieses Gerät freischalten
            </button>
          </div>
        </form>
      )}

      {status.reviewer && (
        <div className="rounded-xl border border-primary/20 bg-primary-soft p-3">
          <div className="flex items-center gap-2 text-[12px] font-semibold text-navy">
            <ShieldCheck className="h-4 w-4 text-primary" /> Spareno Prüfmodus aktiv
          </div>
          <p className="mt-1 text-[11px] text-muted-foreground">
            Dieses Gerät darf interne Märkte und Angebots-QA sehen
            {status.expiresAt ? ` · bis ${new Date(status.expiresAt).toLocaleDateString("de-DE")}` : ""}.
          </p>
          <div className="mt-3 flex gap-2">
            <Link
              to="/pruefung"
              className="flex h-10 flex-1 items-center justify-center gap-1.5 rounded-xl bg-primary text-[12px] font-semibold text-primary-foreground"
            >
              <Wrench className="h-4 w-4" /> Artikelprüfung
            </Link>
            <button
              type="button"
              onClick={lock}
              disabled={busy}
              className="h-10 rounded-xl border border-border bg-surface px-3 text-[12px] font-semibold text-navy"
            >
              Deaktivieren
            </button>
          </div>
        </div>
      )}
    </>
  );
}

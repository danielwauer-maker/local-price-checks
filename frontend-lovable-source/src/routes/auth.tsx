import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { ArrowLeft, LogOut, Mail, RefreshCw } from "lucide-react";
import { supabase } from "@/integrations/supabase/client";
import { useAuth } from "@/lib/use-auth";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

export const Route = createFileRoute("/auth")({
  head: () => ({
    meta: [
      { title: "Anmelden – Spareno" },
      {
        name: "description",
        content:
          "Melde dich an, um Einkaufslisten, Favoriten und deine Märkte geräteübergreifend zu sichern.",
      },
      { property: "og:title", content: "Anmelden – Spareno" },
      {
        property: "og:description",
        content: "Konto für Einkaufslisten, Favoriten und Märkte bei Spareno.",
      },
    ],
  }),
  component: AuthPage,
});

function AuthPage() {
  const navigate = useNavigate();
  const { user, signOut } = useAuth();
  const [mode, setMode] = useState<"login" | "signup" | "forgot">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newPasswordRepeat, setNewPasswordRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmationPending, setConfirmationPending] = useState(false);
  const [resending, setResending] = useState(false);
  const [recoveryMode, setRecoveryMode] = useState(false);

  useEffect(() => {
    const { data } = supabase.auth.onAuthStateChange((event) => {
      if (event === "PASSWORD_RECOVERY") {
        setRecoveryMode(true);
      }
    });
    return () => data.subscription.unsubscribe();
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      if (mode === "login") {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw error;
        toast.success("Willkommen zurück!");
        navigate({ to: "/" });
      } else if (mode === "signup") {
        const { data, error } = await supabase.auth.signUp({
          email,
          password,
          options: { emailRedirectTo: `${window.location.origin}/auth` },
        });
        if (error) throw error;

        if (data.session) {
          toast.success("Konto erstellt und angemeldet.");
          navigate({ to: "/" });
          return;
        }

        setConfirmationPending(true);
        toast.success("Konto erstellt – bitte E-Mail bestätigen.");
      } else {
        const { error } = await supabase.auth.resetPasswordForEmail(email.trim(), {
          redirectTo: `${window.location.origin}/auth`,
        });
        if (error) throw error;
        toast.success("Wenn ein Konto existiert, wurde ein Link zum Zurücksetzen versendet.");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Aktion fehlgeschlagen");
    } finally {
      setBusy(false);
    }
  }

  async function updatePassword(e: React.FormEvent) {
    e.preventDefault();
    if (newPassword.length < 8) {
      toast.error("Das neue Passwort muss mindestens 8 Zeichen lang sein.");
      return;
    }
    if (newPassword !== newPasswordRepeat) {
      toast.error("Die Passwörter stimmen nicht überein.");
      return;
    }

    setBusy(true);
    try {
      const { error } = await supabase.auth.updateUser({ password: newPassword });
      if (error) throw error;
      setRecoveryMode(false);
      setNewPassword("");
      setNewPasswordRepeat("");
      toast.success("Passwort wurde geändert.");
      navigate({ to: "/" });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Passwort konnte nicht geändert werden");
    } finally {
      setBusy(false);
    }
  }

  async function resendConfirmation() {
    if (!email.trim()) return;
    setResending(true);
    try {
      const { error } = await supabase.auth.resend({
        type: "signup",
        email: email.trim(),
        options: { emailRedirectTo: `${window.location.origin}/auth` },
      });
      if (error) throw error;
      toast.success("Bestätigungsmail wurde erneut angefordert.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Bestätigungsmail konnte nicht gesendet werden");
    } finally {
      setResending(false);
    }
  }

  return (
    <div className="min-h-dvh px-5 pt-[max(1.25rem,env(safe-area-inset-top))]">
      <button
        onClick={() => navigate({ to: "/" })}
        className="flex h-10 w-10 items-center justify-center rounded-full bg-surface shadow-card"
        aria-label="Zurück"
      >
        <ArrowLeft className="h-5 w-5" />
      </button>

      {recoveryMode ? (
        <div className="mt-10 surface-card p-6">
          <h1 className="text-2xl font-semibold">Neues Passwort setzen</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Wähle ein neues Passwort für dein Spareno-Konto.
          </p>
          <form onSubmit={updatePassword} className="mt-6 space-y-3">
            <input
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="Neues Passwort"
              className="w-full rounded-2xl bg-surface px-4 py-3.5 text-sm shadow-card outline-none ring-primary/40 focus:ring-2"
            />
            <input
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
              value={newPasswordRepeat}
              onChange={(e) => setNewPasswordRepeat(e.target.value)}
              placeholder="Passwort wiederholen"
              className="w-full rounded-2xl bg-surface px-4 py-3.5 text-sm shadow-card outline-none ring-primary/40 focus:ring-2"
            />
            <button
              type="submit"
              disabled={busy}
              className="w-full rounded-2xl bg-primary py-3.5 text-sm font-semibold text-primary-foreground shadow-float disabled:opacity-60"
            >
              Passwort speichern
            </button>
          </form>
        </div>
      ) : user ? (
        <div className="mt-10 surface-card p-6 text-center">
          <p className="text-sm text-muted-foreground">Angemeldet als</p>
          <p className="mt-1 break-all text-lg font-semibold">{user.email ?? "Spareno-Konto"}</p>
          <p className="mt-2 text-xs text-muted-foreground">
            Diese Anmeldung kann auch aus einer früheren Test-Session stammen.
          </p>
          <button
            onClick={async () => {
              await signOut();
              toast.success("Abgemeldet");
              window.location.assign("/");
            }}
            className="mt-6 inline-flex items-center gap-2 rounded-full bg-secondary px-4 py-2.5 text-sm font-semibold text-secondary-foreground"
          >
            <LogOut className="h-4 w-4" /> Abmelden
          </button>
        </div>
      ) : (
        <>
          <header className="mt-8">
            <h1 className="text-2xl font-semibold">
              {mode === "login" ? "Willkommen zurück" : mode === "signup" ? "Konto erstellen" : "Passwort vergessen"}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {mode === "forgot"
                ? "Wir senden dir einen Link, mit dem du ein neues Passwort festlegen kannst."
                : "Sichere Einkaufslisten, Favoriten und Märkte auf allen Geräten."}
            </p>
          </header>

          {mode !== "forgot" ? (
            <div className="mt-6 flex rounded-2xl bg-secondary p-1">
              {(["login", "signup"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => {
                    setMode(m);
                    setConfirmationPending(false);
                  }}
                  className={cn(
                    "flex-1 rounded-xl py-2 text-sm font-semibold transition-colors",
                    mode === m ? "bg-surface text-foreground shadow-card" : "text-muted-foreground",
                  )}
                >
                  {m === "login" ? "Anmelden" : "Registrieren"}
                </button>
              ))}
            </div>
          ) : null}

          <form onSubmit={submit} className="mt-5 space-y-3">
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="E-Mail"
              className="w-full rounded-2xl bg-surface px-4 py-3.5 text-sm shadow-card outline-none ring-primary/40 focus:ring-2"
            />
            {mode !== "forgot" ? (
              <input
                type="password"
                required
                minLength={6}
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Passwort"
                className="w-full rounded-2xl bg-surface px-4 py-3.5 text-sm shadow-card outline-none ring-primary/40 focus:ring-2"
              />
            ) : null}
            <button
              type="submit"
              disabled={busy}
              className="flex w-full items-center justify-center gap-2 rounded-2xl bg-primary py-3.5 text-sm font-semibold text-primary-foreground shadow-float disabled:opacity-60"
            >
              <Mail className="h-4 w-4" />
              {mode === "login" ? "Anmelden" : mode === "signup" ? "Registrieren" : "Reset-Link senden"}
            </button>
          </form>

          {mode === "login" ? (
            <button
              type="button"
              onClick={() => setMode("forgot")}
              className="mt-3 w-full text-center text-sm font-semibold text-primary"
            >
              Passwort vergessen?
            </button>
          ) : mode === "forgot" ? (
            <button
              type="button"
              onClick={() => setMode("login")}
              className="mt-3 w-full text-center text-sm font-semibold text-primary"
            >
              Zurück zur Anmeldung
            </button>
          ) : null}

          {confirmationPending ? (
            <div className="mt-4 rounded-2xl bg-surface p-4 text-sm shadow-card">
              <p className="font-semibold">E-Mail noch nicht angekommen?</p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                Prüfe bitte auch Spam/Junk. Du kannst die Bestätigungsmail anschließend erneut anfordern.
              </p>
              <button
                type="button"
                onClick={resendConfirmation}
                disabled={resending}
                className="mt-3 inline-flex items-center gap-2 rounded-full bg-secondary px-4 py-2 text-xs font-semibold disabled:opacity-60"
              >
                <RefreshCw className={cn("h-3.5 w-3.5", resending && "animate-spin")} />
                Bestätigungsmail erneut senden
              </button>
            </div>
          ) : null}

          <div className="mt-6 rounded-2xl border border-border bg-surface/60 p-3 text-center text-xs text-muted-foreground">
            Google-Anmeldung ist vorübergehend deaktiviert, bis die OAuth-Credentials für die Produktions-App konfiguriert sind.
          </div>

          <p className="mt-6 text-center text-[11px] text-muted-foreground">
            Ohne Konto kannst du die App weiter nutzen – Daten bleiben dann nur auf diesem Gerät.
          </p>
        </>
      )}
    </div>
  );
}

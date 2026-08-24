import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { ArrowLeft, LogOut, Mail, RefreshCw } from "lucide-react";
import { supabase } from "@/integrations/supabase/client";
import { useAuth } from "@/lib/use-auth";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

export const Route = createFileRoute("/auth")({
  head: () => ({
    meta: [
      { title: "Anmelden – Lokero" },
      {
        name: "description",
        content:
          "Melde dich an, um Einkaufslisten, Favoriten und deine Märkte geräteübergreifend zu sichern.",
      },
      { property: "og:title", content: "Anmelden – Lokero" },
      {
        property: "og:description",
        content: "Konto für Einkaufslisten, Favoriten und Märkte bei Lokero.",
      },
    ],
  }),
  component: AuthPage,
});

function AuthPage() {
  const navigate = useNavigate();
  const { user, signOut } = useAuth();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmationPending, setConfirmationPending] = useState(false);
  const [resending, setResending] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      if (mode === "login") {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw error;
        toast.success("Willkommen zurück!");
        navigate({ to: "/" });
      } else {
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
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Anmeldung fehlgeschlagen");
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

  async function google() {
    setBusy(true);
    try {
      const { error } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: {
          redirectTo: `${window.location.origin}/auth`,
        },
      });
      if (error) throw error;
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Google-Anmeldung fehlgeschlagen");
      setBusy(false);
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

      {user ? (
        <div className="mt-10 surface-card p-6 text-center">
          <p className="text-sm text-muted-foreground">Angemeldet als</p>
          <p className="mt-1 break-all text-lg font-semibold">{user.email ?? "Lokero-Konto"}</p>
          <p className="mt-2 text-xs text-muted-foreground">
            Diese Anmeldung kann auch aus einer früheren Lokero-/Test-Session stammen.
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
              {mode === "login" ? "Willkommen zurück" : "Konto erstellen"}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Sichere Einkaufslisten, Favoriten und Märkte auf allen Geräten.
            </p>
          </header>

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
            <button
              type="submit"
              disabled={busy}
              className="flex w-full items-center justify-center gap-2 rounded-2xl bg-primary py-3.5 text-sm font-semibold text-primary-foreground shadow-float disabled:opacity-60"
            >
              <Mail className="h-4 w-4" />
              {mode === "login" ? "Anmelden" : "Registrieren"}
            </button>
          </form>

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

          <div className="my-5 flex items-center gap-3 text-[11px] uppercase tracking-wide text-muted-foreground">
            <span className="h-px flex-1 bg-border" /> oder <span className="h-px flex-1 bg-border" />
          </div>

          <button
            onClick={google}
            disabled={busy}
            className="flex w-full items-center justify-center gap-2 rounded-2xl bg-surface py-3.5 text-sm font-semibold shadow-card disabled:opacity-60"
          >
            <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden>
              <path
                fill="#4285F4"
                d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.5h6.5a5.6 5.6 0 0 1-2.4 3.7v3h3.9c2.3-2.1 3.5-5.2 3.5-8.9Z"
              />
              <path
                fill="#34A853"
                d="M12 24c3.2 0 6-1.1 8-2.9l-3.9-3c-1.1.7-2.5 1.2-4.1 1.2-3.1 0-5.8-2.1-6.7-5H1.3v3.1A12 12 0 0 0 12 24Z"
              />
              <path fill="#FBBC05" d="M5.3 14.3a7.2 7.2 0 0 1 0-4.6V6.6H1.3a12 12 0 0 0 0 10.8l4-3.1Z" />
              <path
                fill="#EA4335"
                d="M12 4.8c1.8 0 3.3.6 4.6 1.8l3.4-3.4A12 12 0 0 0 1.3 6.6l4 3.1c.9-2.9 3.6-5 6.7-5Z"
              />
            </svg>
            Mit Google fortfahren
          </button>

          <p className="mt-6 text-center text-[11px] text-muted-foreground">
            Ohne Konto kannst du die App weiter nutzen – Daten bleiben dann nur auf diesem Gerät.
          </p>
        </>
      )}
    </div>
  );
}

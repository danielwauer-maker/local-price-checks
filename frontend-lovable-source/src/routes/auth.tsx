import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { ArrowLeft, Mail } from "lucide-react";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

export const Route = createFileRoute("/auth")({
  head: () => ({
    meta: [
      { title: "Anmelden – LocalPrices" },
      { name: "description", content: "Konto für Einkaufslisten, Favoriten und Märkte bei LocalPrices." },
    ],
  }),
  component: AuthPage,
});

function AuthPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  function submit(e: React.FormEvent) {
    e.preventDefault();
    toast("Benutzerkonten werden nach dem MVP aktiviert. Deine aktuellen Daten liegen bereits im LocalPrices-Backend.");
  }

  return (
    <div className="min-h-dvh px-5 pt-[max(1.25rem,env(safe-area-inset-top))]">
      <button onClick={() => navigate({ to: "/" })} className="flex h-10 w-10 items-center justify-center rounded-full bg-surface shadow-card" aria-label="Zurück">
        <ArrowLeft className="h-5 w-5" />
      </button>
      <header className="mt-8">
        <h1 className="text-2xl font-semibold">{mode === "login" ? "Willkommen zurück" : "Konto erstellen"}</h1>
        <p className="mt-1 text-sm text-muted-foreground">Sichere Einkaufslisten, Favoriten und Märkte auf allen Geräten.</p>
      </header>
      <div className="mt-6 flex rounded-2xl bg-secondary p-1">
        {(["login", "signup"] as const).map((m) => (
          <button key={m} onClick={() => setMode(m)} className={cn("flex-1 rounded-xl py-2 text-sm font-semibold transition-colors", mode === m ? "bg-surface text-foreground shadow-card" : "text-muted-foreground")}>{m === "login" ? "Anmelden" : "Registrieren"}</button>
        ))}
      </div>
      <form onSubmit={submit} className="mt-5 space-y-3">
        <input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="E-Mail" className="w-full rounded-2xl bg-surface px-4 py-3.5 text-sm shadow-card outline-none ring-primary/40 focus:ring-2" />
        <input type="password" required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Passwort" className="w-full rounded-2xl bg-surface px-4 py-3.5 text-sm shadow-card outline-none ring-primary/40 focus:ring-2" />
        <button type="submit" className="flex w-full items-center justify-center gap-2 rounded-2xl bg-primary py-3.5 text-sm font-semibold text-primary-foreground shadow-float"><Mail className="h-4 w-4" />{mode === "login" ? "Anmelden" : "Registrieren"}</button>
      </form>
      <div className="my-5 flex items-center gap-3 text-[11px] uppercase tracking-wide text-muted-foreground"><span className="h-px flex-1 bg-border" /> oder <span className="h-px flex-1 bg-border" /></div>
      <button onClick={() => toast("Google-Anmeldung wird nach dem MVP aktiviert.")} className="flex w-full items-center justify-center gap-2 rounded-2xl bg-surface py-3.5 text-sm font-semibold shadow-card">
        <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden><path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.5h6.5a5.6 5.6 0 0 1-2.4 3.7v3h3.9c2.3-2.1 3.5-5.2 3.5-8.9Z"/><path fill="#34A853" d="M12 24c3.2 0 6-1.1 8-2.9l-3.9-3c-1.1.7-2.5 1.2-4.1 1.2-3.1 0-5.8-2.1-6.7-5H1.3v3.1A12 12 0 0 0 12 24Z"/><path fill="#FBBC05" d="M5.3 14.3a7.2 7.2 0 0 1 0-4.6V6.6H1.3a12 12 0 0 0 0 10.8l4-3.1Z"/><path fill="#EA4335" d="M12 4.8c1.8 0 3.3.6 4.6 1.8l3.4-3.4A12 12 0 0 0 1.3 6.6l4 3.1c.9-2.9 3.6-5 6.7-5Z"/></svg>Mit Google fortfahren
      </button>
      <p className="mt-6 text-center text-[11px] text-muted-foreground">Ohne Konto kannst du die App weiter nutzen – deine Daten werden im aktuellen Testsystem gespeichert.</p>
    </div>
  );
}

import { CheckCircle2, MessageCircle, Star, X } from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { apiFetch } from "@/lib/api-client";

const SESSION_KEY = "lp_feedback_session_count";
const ONBOARDING_KEY = "lp_onboarding_v2_completed";

type SavingsValue = "significant" | "some" | "not_yet" | "unsure";
type MonthlyPrice = "1.99" | "2.99" | "4.99" | "9.99" | "none";

const SAVINGS: Array<{ value: SavingsValue; label: string }> = [
  { value: "significant", label: "Ja, deutlich" },
  { value: "some", label: "Ein wenig" },
  { value: "not_yet", label: "Noch nicht" },
  { value: "unsure", label: "Kann ich noch nicht beurteilen" },
];
const PRICES: Array<{ value: MonthlyPrice; label: string }> = [
  { value: "1.99", label: "1,99 €" },
  { value: "2.99", label: "2,99 €" },
  { value: "4.99", label: "4,99 €" },
  { value: "9.99", label: "9,99 €" },
  { value: "none", label: "Ich würde kein Abo abschließen" },
];

function nextSessionCount(): number {
  try {
    const current = Number(window.localStorage.getItem(SESSION_KEY) || "0");
    const next = Number.isFinite(current) ? current + 1 : 1;
    window.localStorage.setItem(SESSION_KEY, String(next));
    return next;
  } catch {
    return 1;
  }
}
function onboardingCompleted(): boolean {
  try { return window.localStorage.getItem(ONBOARDING_KEY) === "1"; } catch { return false; }
}

export function PricingFeedbackBadge() {
  const [eligible, setEligible] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [savings, setSavings] = useState<SavingsValue | null>(null);
  const [price, setPrice] = useState<MonthlyPrice | null>(null);
  const [rating, setRating] = useState<number>(0);
  const [comment, setComment] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const sessions = nextSessionCount();
    setEligible(sessions >= 2 && onboardingCompleted());
    void apiFetch("/api/client/feedback")
      .then(async (response) => {
        if (!response.ok) return;
        const data = await response.json();
        if (data?.savingsValue) setSavings(data.savingsValue);
        if (data?.monthlyPrice) setPrice(data.monthlyPrice);
        if (data?.rating) setRating(data.rating);
        if (data?.comment) setComment(data.comment);
        if (data?.submitted && !data?.ratingSubmitted) setStep(3);
        setSubmitted(Boolean(data?.submitted && data?.ratingSubmitted));
      })
      .catch(() => undefined);
  }, []);

  async function submit() {
    if (!savings || !price || rating < 1) return;
    setSaving(true);
    setError("");
    try {
      const response = await apiFetch("/api/client/feedback", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ savingsValue: savings, monthlyPrice: price, rating, comment }),
      });
      if (!response.ok) throw new Error("feedback failed");
      setSubmitted(true);
      setOpen(false);
    } catch {
      setError("Deine Antwort konnte gerade nicht gespeichert werden. Bitte versuche es später noch einmal.");
    } finally { setSaving(false); }
  }

  if (!eligible || submitted || typeof document === "undefined") return null;

  const badge = (
    <button
      type="button"
      onClick={() => setOpen(true)}
      className="fixed right-0 flex items-center gap-1.5 rounded-l-xl border border-r-0 border-primary/15 bg-primary px-2.5 py-2 text-xs font-semibold text-primary-foreground shadow-lg"
      style={{ top: "64%", zIndex: 2147483000 }}
      aria-label="Deine Meinung zu LocalPrices"
    >
      <MessageCircle className="h-4 w-4" />
      <span className="[writing-mode:vertical-rl] rotate-180">Deine Meinung</span>
    </button>
  );

  if (!open) return createPortal(badge, document.body);

  const sheet = (
    <div className="fixed inset-0 flex items-end justify-center bg-black/35" style={{ zIndex: 2147483646 }} onClick={() => setOpen(false)}>
      <section className="w-full max-w-[460px] rounded-t-[2rem] bg-background px-5 pb-[max(1.5rem,env(safe-area-inset-bottom))] pt-5 shadow-2xl" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Kurze LocalPrices-Abstimmung">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div><p className="text-xs font-semibold uppercase tracking-[0.12em] text-primary">Kurze Abstimmung</p><h2 className="mt-1 font-display text-2xl font-semibold text-foreground">Hilf uns, LocalPrices besser zu machen</h2></div>
          <button type="button" onClick={() => setOpen(false)} className="rounded-full p-2 text-muted-foreground hover:bg-muted" aria-label="Schließen"><X className="h-5 w-5" /></button>
        </div>
        <p className="mb-5 text-sm leading-6 text-muted-foreground">LocalPrices soll dir helfen, durch günstigere Angebote, passende Märkte und einen besseren Einkaufsplan regelmäßig Geld zu sparen.</p>

        {step === 1 && <div><h3 className="mb-3 text-base font-semibold">Hilft dir LocalPrices beim Sparen?</h3><div className="space-y-2">{SAVINGS.map((item) => <button key={item.value} type="button" onClick={() => { setSavings(item.value); setStep(2); }} className="flex w-full items-center justify-between rounded-2xl border border-border bg-surface px-4 py-3 text-left text-sm font-medium hover:border-primary/40">{item.label}<span className="text-muted-foreground">›</span></button>)}</div></div>}

        {step === 2 && <div>
          <button type="button" onClick={() => setStep(1)} className="mb-3 text-xs font-medium text-muted-foreground">← Zurück</button>
          <h3 className="mb-1 text-base font-semibold">Welchen monatlichen Preis würdest du noch als fair empfinden?</h3>
          <p className="mb-3 text-xs leading-5 text-muted-foreground">Nur eine kurze Einschätzung – es wird natürlich nichts gebucht.</p>
          <div className="grid grid-cols-2 gap-2">{PRICES.map((item) => <button key={item.value} type="button" onClick={() => setPrice(item.value)} className={`rounded-2xl border px-3 py-3 text-sm font-semibold ${price === item.value ? "border-primary bg-primary/10 text-primary" : "border-border bg-surface text-foreground"} ${item.value === "none" ? "col-span-2" : ""}`}>{item.label}</button>)}</div>
          <button type="button" onClick={() => setStep(3)} disabled={!price} className="mt-4 w-full rounded-2xl bg-primary px-4 py-3.5 text-sm font-semibold text-primary-foreground disabled:opacity-50">Weiter</button>
        </div>}

        {step === 3 && <div>
          <button type="button" onClick={() => setStep(2)} className="mb-3 text-xs font-medium text-muted-foreground">← Zurück</button>
          <h3 className="text-base font-semibold">Wie gefällt dir LocalPrices bisher?</h3>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">Tippe auf die Sterne. Ein Verbesserungsvorschlag ist optional.</p>
          <div className="my-4 flex justify-center gap-2" aria-label={`${rating} von 5 Sternen`}>{[1,2,3,4,5].map((value) => <button key={value} type="button" onClick={() => setRating(value)} className="rounded-lg p-1" aria-label={`${value} Sterne`}><Star className={`h-9 w-9 ${value <= rating ? "fill-primary text-primary" : "text-border"}`} /></button>)}</div>
          <textarea value={comment} onChange={(e) => setComment(e.target.value.slice(0,1000))} rows={3} placeholder="Was sollten wir verbessern oder was fehlt dir? (optional)" className="w-full resize-none rounded-2xl border border-border bg-surface px-3 py-3 text-sm outline-none focus:border-primary" />
          <div className="mt-1 text-right text-[10px] text-muted-foreground">{comment.length}/1000</div>
          {error && <p className="mt-2 text-xs leading-5 text-destructive">{error}</p>}
          <button type="button" onClick={() => void submit()} disabled={rating < 1 || saving} className="mt-3 flex w-full items-center justify-center gap-2 rounded-2xl bg-primary px-4 py-3.5 text-sm font-semibold text-primary-foreground disabled:opacity-50"><CheckCircle2 className="h-4 w-4" /> {saving ? "Speichere …" : "Feedback senden"}</button>
        </div>}
      </section>
    </div>
  );
  return createPortal(<>{badge}{sheet}</>, document.body);
}

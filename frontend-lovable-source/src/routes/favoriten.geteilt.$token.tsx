import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Heart, HeartHandshake, LogIn, Save, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/AppShell";
import { fetchPublicFavoriteShare, subscribeToFavoriteShare } from "@/services/sharing-api";

export const Route = createFileRoute("/favoriten/geteilt/$token")({
  head: () => ({ meta: [{ title: "Geteilte Favoriten – Spareno" }] }),
  component: PublicFavoriteShareScreen,
});

function PublicFavoriteShareScreen() {
  const { token } = Route.useParams();
  const share = useQuery({ queryKey: ["public-favorites", token], queryFn: () => fetchPublicFavoriteShare(token) });
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [accountNeeded, setAccountNeeded] = useState(false);

  const save = async () => {
    setBusy(true);
    setAccountNeeded(false);
    try {
      await subscribeToFavoriteShare(token);
      setSaved(true);
      toast.success("Favoriten von Freunden in Spareno gespeichert");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Favoriten konnten nicht gespeichert werden";
      if (message.toLowerCase().includes("account")) setAccountNeeded(true);
      else toast.error(message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHeader title="Geteilte Favoriten" />
      <div className="space-y-3 px-4 pt-3">
        {share.isLoading && <div className="card-surface h-36 animate-pulse" />}
        {share.isError && (
          <section className="card-surface p-5 text-center">
            <HeartHandshake className="mx-auto h-7 w-7 text-muted-foreground" />
            <h1 className="mt-3 text-[16px] font-semibold text-navy">Freigabe nicht gefunden</h1>
            <p className="mt-1 text-[11px] text-muted-foreground">Der Link ist nicht mehr gültig oder wurde erneuert.</p>
          </section>
        )}

        {share.data && (
          <>
            <section className="card-surface p-5 text-center">
              <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-primary-soft text-primary"><HeartHandshake className="h-6 w-6" /></span>
              <h1 className="mt-3 text-[18px] font-bold text-navy">Favoriten von {share.data.ownerName}</h1>
              <p className="mx-auto mt-1 max-w-[315px] text-[11px] leading-relaxed text-muted-foreground">
                {share.data.available
                  ? "Hier siehst du nur die Lieblingsprodukte, die diese Person bewusst für Freunde freigegeben hat."
                  : `${share.data.ownerName} teilt die Favoriten derzeit nicht. Wenn die Liste später wieder sichtbar wird, bleibt ein gespeicherter Kontakt erhalten.`}
              </p>
              {share.data.available && (
                <button type="button" disabled={busy || saved} onClick={() => void save()} className={`mt-4 inline-flex h-11 items-center gap-2 rounded-xl px-4 text-[12px] font-semibold ${saved ? "border border-primary/20 bg-primary-soft text-primary" : "bg-primary text-primary-foreground"}`}>
                  {saved ? <Heart className="h-4 w-4 fill-current" /> : <Save className="h-4 w-4" />}
                  {saved ? "In Favoriten von Freunden gespeichert" : "In Spareno speichern"}
                </button>
              )}
              {accountNeeded && (
                <div className="mt-3 rounded-xl border border-primary/15 bg-primary-soft/50 p-3">
                  <p className="text-[10px] leading-relaxed text-muted-foreground">Zum dauerhaften Speichern brauchst du einen Spareno-Account. Anschauen kannst du diese Freigabe weiterhin ohne Anmeldung.</p>
                  <Link to="/auth" className="mt-2 inline-flex items-center gap-1.5 text-[11px] font-semibold text-primary"><LogIn className="h-3.5 w-3.5" /> Anmelden oder registrieren</Link>
                </div>
              )}
            </section>

            {share.data.available && (
              <section>
                <div className="mb-2 flex items-center justify-between"><h2 className="text-[13px] font-semibold text-navy">Freigegebene Lieblingsprodukte</h2><span className="text-[10px] text-muted-foreground">{share.data.items.length}</span></div>
                <div className="card-surface divide-y divide-border">
                  {share.data.items.length === 0 && <p className="px-4 py-5 text-center text-[11px] text-muted-foreground">Aktuell sind keine einzelnen Favoriten sichtbar.</p>}
                  {share.data.items.map((product) => (
                    <div key={product.id} className="flex items-center gap-3 px-3 py-3">
                      <div className="grid h-12 w-12 shrink-0 place-items-center overflow-hidden rounded-xl bg-muted-surface">{product.imageUrl ? <img src={product.imageUrl} alt="" className="h-full w-full object-contain p-1" /> : <Heart className="h-4.5 w-4.5 text-primary" />}</div>
                      <div className="min-w-0 flex-1"><p className="line-clamp-2 text-[11px] font-semibold leading-snug text-navy">{product.name}</p><p className="mt-0.5 text-[9px] text-muted-foreground">{[product.brand, product.amount].filter(Boolean).join(" · ")}</p></div>
                      <Heart className="h-4 w-4 shrink-0 fill-discount/15 text-discount" />
                    </div>
                  ))}
                </div>
              </section>
            )}

            <section className="flex gap-2 rounded-xl border border-border bg-muted-surface/55 p-3"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" /><p className="text-[10px] leading-relaxed text-muted-foreground">Diese Ansicht enthält keine E-Mail-Adresse, keinen Standort, keine Märkte und keine Einkaufsliste der teilenden Person.</p></section>
          </>
        )}
      </div>
    </div>
  );
}

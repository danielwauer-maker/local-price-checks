import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, ListChecks, LogIn, Users } from "lucide-react";
import { useState } from "react";
import { PageHeader } from "@/components/AppShell";
import { useStore } from "@/lib/app-store";
import { acceptShoppingListInvite, inspectShoppingListInvite } from "@/services/sharing-api";

export const Route = createFileRoute("/liste/einladung/$token")({
  head: () => ({ meta: [{ title: "Einladung zur Einkaufsliste – Spareno" }] }),
  component: ShoppingListInviteScreen,
});

function ShoppingListInviteScreen() {
  const { token } = Route.useParams();
  const navigate = useNavigate();
  const { refreshShoppingSharing } = useStore();
  const [error, setError] = useState<string | null>(null);
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const invite = useQuery({ queryKey: ["shopping-list-invite", token], queryFn: () => inspectShoppingListInvite(token) });

  const accept = async () => {
    setBusy(true);
    setError(null);
    try {
      await acceptShoppingListInvite(token);
      await refreshShoppingSharing();
      setAccepted(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Einladung konnte nicht angenommen werden.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHeader title="Einladung" />
      <div className="px-4 pt-4">
        <section className="card-surface p-5 text-center">
          <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-primary-soft text-primary">
            {accepted ? <CheckCircle2 className="h-6 w-6" /> : <Users className="h-6 w-6" />}
          </span>

          {invite.isLoading && <p className="mt-4 text-[12px] text-muted-foreground">Einladung wird geprüft …</p>}
          {invite.isError && <><h1 className="mt-4 text-[17px] font-semibold text-navy">Einladung nicht verfügbar</h1><p className="mt-1 text-[12px] text-muted-foreground">Der Link ist ungültig oder wurde bereits zurückgezogen.</p></>}

          {invite.data && !accepted && (
            <>
              <h1 className="mt-4 text-[18px] font-bold text-navy">{invite.data.listName}</h1>
              <p className="mx-auto mt-1 max-w-[310px] text-[12px] leading-relaxed text-muted-foreground">
                {invite.data.inviter} möchte diese Einkaufsliste mit dir teilen. Änderungen werden bei euch beiden fast in Echtzeit synchronisiert.
              </p>
              {invite.data.invitedEmail && <p className="mt-3 rounded-lg bg-muted-surface px-3 py-2 text-[10px] text-muted-foreground">Einladung für {invite.data.invitedEmail}</p>}
              {!invite.data.valid ? (
                <p className="mt-4 text-[12px] font-medium text-destructive">Diese Einladung ist nicht mehr gültig.</p>
              ) : (
                <button type="button" disabled={busy} onClick={() => void accept()} className="mt-5 flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-primary text-[13px] font-semibold text-primary-foreground disabled:opacity-50">
                  <ListChecks className="h-4.5 w-4.5" /> {busy ? "Wird verbunden …" : "Einkaufsliste beitreten"}
                </button>
              )}
              {error && (
                <div className="mt-3 rounded-xl border border-destructive/15 bg-destructive/5 p-3 text-left">
                  <p className="text-[11px] text-destructive">{error}</p>
                  {error.toLowerCase().includes("account") && <Link to="/auth" className="mt-2 inline-flex items-center gap-1.5 text-[11px] font-semibold text-primary"><LogIn className="h-3.5 w-3.5" /> Anmelden oder registrieren</Link>}
                </div>
              )}
            </>
          )}

          {accepted && (
            <>
              <h1 className="mt-4 text-[18px] font-bold text-navy">Ihr kauft jetzt gemeinsam ein</h1>
              <p className="mx-auto mt-1 max-w-[310px] text-[12px] leading-relaxed text-muted-foreground">Die geteilte Liste ist jetzt deine aktive Einkaufsliste. Neue Artikel aus Angeboten landen automatisch dort.</p>
              <button type="button" onClick={() => navigate({ to: "/liste" })} className="mt-5 h-12 w-full rounded-xl bg-primary text-[13px] font-semibold text-primary-foreground">Gemeinsame Liste öffnen</button>
            </>
          )}
        </section>
      </div>
    </div>
  );
}

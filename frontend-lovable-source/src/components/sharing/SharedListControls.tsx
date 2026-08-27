import { Link } from "@tanstack/react-router";
import { Check, ChevronDown, Copy, Link2, Plus, Share2, Trash2, UserPlus, Users, X } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { useStore } from "@/lib/app-store";
import { createShoppingListInvite, removeShoppingListMember, shoppingInviteUrl, type ListInvite } from "@/services/sharing-api";

export function SharedListControls() {
  const {
    sharingEnabled,
    shoppingLists,
    activeShoppingListId,
    activeShoppingListName,
    activeShoppingListMembers,
    selectShoppingList,
    createSharedShoppingList,
    refreshShoppingSharing,
  } = useStore();
  const [pickerOpen, setPickerOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [invite, setInvite] = useState<ListInvite | null>(null);
  const [busy, setBusy] = useState(false);

  const active = useMemo(
    () => shoppingLists.find((list) => list.id === activeShoppingListId),
    [shoppingLists, activeShoppingListId],
  );
  const memberCount = activeShoppingListMembers.length || active?.memberCount || 1;

  if (!sharingEnabled) {
    return (
      <Link
        to="/auth"
        className="mt-2 flex w-full items-center gap-2 rounded-xl border border-primary/15 bg-primary-soft/60 px-3 py-2 text-left"
      >
        <Users className="h-4 w-4 shrink-0 text-primary" />
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-semibold text-navy">Einkaufsliste gemeinsam nutzen</p>
          <p className="text-[10px] text-muted-foreground">Mit Account nahezu live mit Partnern oder Freunden teilen</p>
        </div>
        <ChevronDown className="h-4 w-4 -rotate-90 text-primary" />
      </Link>
    );
  }

  const createList = async () => {
    const name = newName.trim();
    if (!name) return;
    setBusy(true);
    try {
      await createSharedShoppingList(name);
      setNewName("");
      setPickerOpen(false);
      toast.success(`${name} ist jetzt deine aktive Liste`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Liste konnte nicht erstellt werden");
    } finally {
      setBusy(false);
    }
  };

  const createInvite = async () => {
    if (!activeShoppingListId) return;
    setBusy(true);
    try {
      const created = await createShoppingListInvite(activeShoppingListId, inviteEmail || undefined);
      setInvite(created);
      toast.success("Einladungslink erstellt");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Einladung konnte nicht erstellt werden");
    } finally {
      setBusy(false);
    }
  };

  const copyInvite = async () => {
    if (!invite) return;
    await navigator.clipboard.writeText(shoppingInviteUrl(invite.token));
    toast.success("Einladungslink kopiert");
  };

  const shareInvite = async () => {
    if (!invite) return;
    const url = shoppingInviteUrl(invite.token);
    if (navigator.share) {
      await navigator.share({ title: `${invite.listName} – Spareno`, text: "Komm auf meine gemeinsame Spareno-Einkaufsliste.", url });
    } else {
      await copyInvite();
    }
  };

  const removeMember = async (userId: string, displayName: string) => {
    if (!activeShoppingListId) return;
    if (!window.confirm(`${displayName} wirklich aus dieser Einkaufsliste entfernen?`)) return;
    setBusy(true);
    try {
      await removeShoppingListMember(activeShoppingListId, userId);
      await refreshShoppingSharing();
      toast.success(`${displayName} wurde aus der Liste entfernt`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Mitglied konnte nicht entfernt werden");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="mt-2 flex items-stretch gap-2">
        <button
          type="button"
          onClick={() => setPickerOpen(true)}
          className="flex min-w-0 flex-1 items-center gap-2 rounded-xl border border-border bg-muted-surface/65 px-3 py-2 text-left"
        >
          <span className="relative grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-primary-soft text-primary">
            <Users className="h-4 w-4" />
            {memberCount > 1 && <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full border border-surface bg-success" />}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[12px] font-semibold text-navy">{activeShoppingListName}</p>
            <p className="truncate text-[10px] text-muted-foreground">
              {memberCount > 1 ? `${memberCount} Personen · Live synchronisiert` : "Nur du · weitere Listen möglich"}
            </p>
          </div>
          <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
        </button>
        {active?.role === "owner" && (
          <button
            type="button"
            onClick={() => { setInvite(null); setShareOpen(true); }}
            className="grid w-12 shrink-0 place-items-center rounded-xl border border-primary/20 bg-primary-soft text-primary"
            aria-label="Einkaufsliste teilen und Mitglieder verwalten"
          >
            <UserPlus className="h-4.5 w-4.5" />
          </button>
        )}
      </div>

      {pickerOpen && (
        <div className="fixed inset-0 z-[80] flex items-end bg-navy/35" onClick={() => setPickerOpen(false)}>
          <div className="w-full max-w-[430px] rounded-t-3xl bg-surface p-4 pb-[max(1rem,env(safe-area-inset-bottom))]" onClick={(event) => event.stopPropagation()}>
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h2 className="text-[16px] font-semibold text-navy">Einkaufslisten</h2>
                <p className="text-[11px] text-muted-foreground">Neue Artikel landen automatisch in der aktiven Liste.</p>
              </div>
              <button type="button" onClick={() => setPickerOpen(false)} className="grid h-9 w-9 place-items-center"><X className="h-5 w-5" /></button>
            </div>
            <div className="space-y-2">
              {shoppingLists.map((list) => {
                const selected = list.id === activeShoppingListId;
                return (
                  <button
                    key={list.id}
                    type="button"
                    onClick={async () => {
                      if (selected) return setPickerOpen(false);
                      setBusy(true);
                      try {
                        await selectShoppingList(list.id);
                        setPickerOpen(false);
                      } catch (error) {
                        toast.error(error instanceof Error ? error.message : "Liste konnte nicht gewechselt werden");
                      } finally {
                        setBusy(false);
                      }
                    }}
                    className={`flex w-full items-center gap-3 rounded-xl border px-3 py-3 text-left ${selected ? "border-primary bg-primary-soft/55" : "border-border bg-surface"}`}
                  >
                    <Users className={`h-4 w-4 ${selected ? "text-primary" : "text-muted-foreground"}`} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[12px] font-semibold text-navy">{list.name}</p>
                      <p className="text-[10px] text-muted-foreground">{list.memberCount > 1 ? `${list.memberCount} Personen` : "Nur du"}{list.role !== "owner" ? " · geteilt mit dir" : ""}</p>
                    </div>
                    {selected && <Check className="h-4 w-4 text-primary" />}
                  </button>
                );
              })}
            </div>
            <div className="mt-4 border-t border-border pt-4">
              <label className="mb-1.5 block text-[11px] font-semibold text-navy" htmlFor="new-list-name">Neue Liste</label>
              <div className="flex gap-2">
                <input id="new-list-name" value={newName} onChange={(event) => setNewName(event.target.value)} placeholder="z. B. Familie oder Grillabend" maxLength={120} className="h-11 min-w-0 flex-1 rounded-xl border border-border bg-muted-surface px-3 text-[12px] outline-none focus:border-primary" />
                <button type="button" disabled={!newName.trim() || busy} onClick={() => void createList()} className="inline-flex h-11 items-center gap-1.5 rounded-xl bg-primary px-3 text-[12px] font-semibold text-primary-foreground disabled:opacity-40"><Plus className="h-4 w-4" /> Erstellen</button>
              </div>
              <p className="mt-2 text-[9px] leading-relaxed text-muted-foreground">Du musst beim Hinzufügen eines Angebots nichts auswählen: Spareno verwendet immer die zuletzt aktive Liste.</p>
            </div>
          </div>
        </div>
      )}

      {shareOpen && active && (
        <div className="fixed inset-0 z-[80] flex items-end bg-navy/35" onClick={() => setShareOpen(false)}>
          <div className="w-full max-w-[430px] rounded-t-3xl bg-surface p-4 pb-[max(1rem,env(safe-area-inset-bottom))]" onClick={(event) => event.stopPropagation()}>
            <div className="flex items-start justify-between gap-3">
              <div><h2 className="text-[16px] font-semibold text-navy">{active.name} teilen</h2><p className="mt-0.5 text-[11px] text-muted-foreground">Änderungen werden bei allen Mitgliedern fast sofort aktualisiert.</p></div>
              <button type="button" onClick={() => setShareOpen(false)} className="grid h-9 w-9 place-items-center"><X className="h-5 w-5" /></button>
            </div>
            <div className="mt-4 rounded-xl bg-primary-soft/55 p-3">
              <p className="text-[11px] font-semibold text-navy">Mitglieder · {activeShoppingListMembers.length}</p>
              <div className="mt-2 space-y-1.5">
                {activeShoppingListMembers.map((member) => (
                  <div key={member.userId} className="flex items-center gap-2 rounded-xl border border-primary/10 bg-surface px-2.5 py-2">
                    <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-primary-soft text-[10px] font-bold text-primary">{member.displayName.trim().charAt(0).toUpperCase() || "S"}</span>
                    <div className="min-w-0 flex-1"><p className="truncate text-[10px] font-semibold text-navy">{member.displayName}</p><p className="truncate text-[9px] text-muted-foreground">{member.role === "owner" ? "Besitzer" : member.email || "Kann Liste bearbeiten"}</p></div>
                    {member.role !== "owner" && <button type="button" disabled={busy} onClick={() => void removeMember(member.userId, member.displayName)} className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-muted-foreground hover:bg-destructive/5 hover:text-destructive" aria-label={`${member.displayName} entfernen`}><Trash2 className="h-3.5 w-3.5" /></button>}
                  </div>
                ))}
              </div>
            </div>
            {!invite ? (
              <div className="mt-4">
                <label htmlFor="invite-email" className="mb-1.5 block text-[11px] font-semibold text-navy">E-Mail optional</label>
                <input id="invite-email" type="email" value={inviteEmail} onChange={(event) => setInviteEmail(event.target.value)} placeholder="person@beispiel.de" className="h-11 w-full rounded-xl border border-border bg-muted-surface px-3 text-[12px] outline-none focus:border-primary" />
                <p className="mt-1.5 text-[10px] leading-relaxed text-muted-foreground">Ohne E-Mail kann jede Person mit dem privaten Einladungslink beitreten. Mit E-Mail ist die Einladung an dieses Konto gebunden.</p>
                <button type="button" disabled={busy} onClick={() => void createInvite()} className="mt-3 flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-primary text-[12px] font-semibold text-primary-foreground disabled:opacity-50"><Link2 className="h-4 w-4" /> Privaten Einladungslink erstellen</button>
              </div>
            ) : (
              <div className="mt-4">
                <div className="rounded-xl border border-success/25 bg-success/5 p-3"><p className="text-[11px] font-semibold text-navy">Einladung bereit</p><p className="mt-1 break-all text-[10px] text-muted-foreground">{shoppingInviteUrl(invite.token)}</p></div>
                <div className="mt-3 grid grid-cols-2 gap-2">
                  <button type="button" onClick={() => void copyInvite()} className="flex h-11 items-center justify-center gap-2 rounded-xl border border-border bg-surface text-[12px] font-semibold text-navy"><Copy className="h-4 w-4" /> Kopieren</button>
                  <button type="button" onClick={() => void shareInvite()} className="flex h-11 items-center justify-center gap-2 rounded-xl bg-primary text-[12px] font-semibold text-primary-foreground"><Share2 className="h-4 w-4" /> Teilen</button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}

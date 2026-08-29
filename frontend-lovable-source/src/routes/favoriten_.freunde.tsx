import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { BellRing, Bell, BellOff, ChevronLeft, Heart, HeartHandshake, Trash2, Users } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/AppShell";
import { fetchFriendFavorites, unsubscribeFromFavoriteShare, updateFriendFavoriteSettings } from "@/services/sharing-api";

export const Route = createFileRoute("/favoriten_/freunde")({
  head: () => ({ meta: [{ title: "Favoriten von Freunden – Spareno" }] }),
  component: FriendFavoritesScreen,
});

function MiniToggle({ checked, onChange, label }: { checked: boolean; onChange: (value: boolean) => void; label: string }) {
  return <button type="button" role="switch" aria-checked={checked} aria-label={label} onClick={() => onChange(!checked)} className={`relative h-6 w-10 shrink-0 rounded-full ${checked ? "bg-primary" : "bg-border"}`}><span className={`absolute top-1 h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${checked ? "translate-x-5" : "translate-x-1"}`} /></button>;
}

function FriendFavoritesScreen() {
  const overview = useQuery({ queryKey: ["friend-favorites"], queryFn: fetchFriendFavorites, refetchInterval: 20_000 });
  const refresh = () => overview.refetch();

  const changeSetting = async (shareId: string, patch: { inAppEnabled?: boolean; pushEnabled?: boolean }) => {
    try {
      await updateFriendFavoriteSettings(shareId, patch);
      await refresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Einstellung konnte nicht gespeichert werden");
    }
  };

  const remove = async (shareId: string, name: string) => {
    if (!window.confirm(`Favoriten von ${name} wirklich entfernen?`)) return;
    try {
      await unsubscribeFromFavoriteShare(shareId);
      await refresh();
      toast.success(`${name} wurde aus deinen Freundesfavoriten entfernt`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Verknüpfung konnte nicht entfernt werden");
    }
  };

  return (
    <div>
      <PageHeader title="Favoriten von Freunden" subtitle="Gespeicherte Vorlieben & passende Angebote" />
      <div className="px-4 pt-3">
        <Link to="/favoriten" className="inline-flex h-9 items-center gap-1 rounded-xl border border-border bg-surface px-3 text-[11px] font-semibold text-navy">
          <ChevronLeft className="h-4 w-4" /> Zurück zu Favoriten
        </Link>
      </div>
      <div className="space-y-4 px-4 pt-3">
        {overview.isLoading && <div className="card-surface h-28 animate-pulse" />}

        {overview.data?.alerts && overview.data.alerts.length > 0 && (
          <section>
            <div className="mb-2 flex items-center gap-1.5"><BellRing className="h-4 w-4 text-discount" /><h2 className="text-[13px] font-semibold text-navy">Gerade im Angebot</h2></div>
            <div className="space-y-2">
              {overview.data.alerts.map((alert, index) => (
                <div key={`${alert.shareId}-${alert.product?.id ?? index}`} className="flex items-center gap-3 rounded-2xl border border-discount/15 bg-discount/[0.055] p-3">
                  <div className="grid h-12 w-12 shrink-0 place-items-center overflow-hidden rounded-xl bg-surface">
                    {alert.product?.imageUrl ? <img src={alert.product.imageUrl} alt="" className="h-full w-full object-contain p-1" /> : <Heart className="h-5 w-5 text-discount" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-[9px] font-semibold uppercase tracking-wide text-discount">Favorit von {alert.friendName}</p>
                    <p className="line-clamp-2 text-[11px] font-semibold leading-snug text-navy">{alert.product?.name ?? "Lieblingsprodukt"}</p>
                    <p className="mt-0.5 truncate text-[9px] text-muted-foreground">{alert.market?.name ?? "Dein Markt"}</p>
                  </div>
                  <span className="tabular shrink-0 text-[15px] font-bold text-navy">{alert.price.toFixed(2).replace(".", ",")} €</span>
                </div>
              ))}
            </div>
          </section>
        )}

        {overview.data && overview.data.friends.length === 0 && (
          <section className="card-surface p-5 text-center">
            <span className="mx-auto grid h-11 w-11 place-items-center rounded-xl bg-primary-soft text-primary"><Users className="h-5 w-5" /></span>
            <h2 className="mt-3 text-[15px] font-semibold text-navy">Noch keine Freundesfavoriten</h2>
            <p className="mx-auto mt-1 max-w-[310px] text-[11px] leading-relaxed text-muted-foreground">Öffne den Favoriten-Link oder QR-Code eines Freundes und speichere ihn in Spareno. Danach siehst du hier nur die Produkte, die diese Person freigegeben hat.</p>
          </section>
        )}

        {(overview.data?.friends ?? []).map((friend) => (
          <section key={friend.shareId} className="overflow-hidden rounded-2xl border border-border bg-surface">
            <div className="flex items-center gap-3 border-b border-border bg-muted-surface/55 px-3 py-3">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-primary-soft text-primary"><HeartHandshake className="h-5 w-5" /></span>
              <div className="min-w-0 flex-1"><h2 className="truncate text-[13px] font-semibold text-navy">{friend.ownerName}</h2><p className="text-[10px] text-muted-foreground">{friend.available ? `${friend.visibleCount} sichtbare Favoriten` : "teilt Favoriten derzeit nicht"}</p></div>
              <button type="button" onClick={() => void remove(friend.shareId, friend.ownerName)} className="grid h-9 w-9 place-items-center rounded-xl text-muted-foreground" aria-label={`${friend.ownerName} entfernen`}><Trash2 className="h-4 w-4" /></button>
            </div>

            {friend.available ? (
              <div className="divide-y divide-border">
                {friend.items.filter(Boolean).map((product) => product && (
                  <div key={product.id} className="flex items-center gap-3 px-3 py-2.5">
                    <div className="grid h-10 w-10 shrink-0 place-items-center overflow-hidden rounded-lg bg-muted-surface">{product.imageUrl ? <img src={product.imageUrl} alt="" className="h-full w-full object-contain p-1" /> : <Heart className="h-4 w-4 text-primary" />}</div>
                    <div className="min-w-0 flex-1"><p className="line-clamp-2 text-[11px] font-medium leading-snug text-navy">{product.name}</p>{product.brand && <p className="mt-0.5 text-[9px] text-muted-foreground">{product.brand}</p>}</div>
                  </div>
                ))}
              </div>
            ) : <p className="px-4 py-5 text-center text-[11px] text-muted-foreground">Die Verbindung bleibt bestehen. Sobald {friend.ownerName} die Liste wieder sichtbar macht, erscheinen die Favoriten hier automatisch.</p>}

            <div className="space-y-2 border-t border-border px-3 py-3">
              <div className="flex items-center gap-2"><span className="grid h-7 w-7 place-items-center rounded-lg bg-primary-soft text-primary">{friend.inAppEnabled ? <Bell className="h-3.5 w-3.5" /> : <BellOff className="h-3.5 w-3.5" />}</span><div className="min-w-0 flex-1"><p className="text-[10px] font-semibold text-navy">In-App-Hinweise</p><p className="text-[9px] text-muted-foreground">Hinweis, wenn ein sichtbarer Favorit in deinen Märkten im Angebot ist</p></div><MiniToggle checked={friend.inAppEnabled} onChange={(next) => void changeSetting(friend.shareId, { inAppEnabled: next })} label={`In-App-Hinweise für ${friend.ownerName}`} /></div>
              <div className="flex items-center gap-2"><span className="grid h-7 w-7 place-items-center rounded-lg bg-muted-surface text-muted-foreground"><BellRing className="h-3.5 w-3.5" /></span><div className="min-w-0 flex-1"><p className="text-[10px] font-semibold text-navy">Push vormerken</p><p className="text-[9px] text-muted-foreground">Wird automatisch genutzt, sobald Freundes-Push aktiviert wird</p></div><MiniToggle checked={friend.pushEnabled} onChange={(next) => void changeSetting(friend.shareId, { pushEnabled: next })} label={`Push für ${friend.ownerName} vormerken`} /></div>
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

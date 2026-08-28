import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, Copy, Eye, EyeOff, HeartHandshake, LockKeyhole, LogIn, QrCode, RefreshCw, Share2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/AppShell";
import {
  favoriteShareQrUrl,
  favoriteShareUrl,
  fetchFavoriteShareSettings,
  rotateFavoriteShare,
  setFavoriteShareEnabled,
  setSharedFavoriteVisibility,
} from "@/services/sharing-api";

export const Route = createFileRoute("/favoriten/teilen")({
  head: () => ({ meta: [{ title: "Favoriten teilen – Spareno" }] }),
  component: FavoriteShareScreen,
});

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (value: boolean) => void; label: string }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} onClick={() => onChange(!checked)} className={`relative h-7 w-12 shrink-0 overflow-hidden rounded-full border transition-colors ${checked ? "border-primary bg-primary" : "border-border bg-muted-surface"}`}>
      <span className={`absolute left-1 top-1 h-5 w-5 rounded-full bg-white shadow-sm transition-transform ${checked ? "translate-x-5" : "translate-x-0"}`} />
    </button>
  );
}

function FavoriteShareScreen() {
  const settings = useQuery({ queryKey: ["favorite-share-settings"], queryFn: fetchFavoriteShareSettings });
  const [busy, setBusy] = useState(false);

  const refresh = () => Promise.all([settings.refetch()]);
  const share = settings.data?.share;

  const enableSharing = async () => {
    setBusy(true);
    try {
      await setFavoriteShareEnabled(true);
      await refresh();
      toast.success("Deine freigegebenen Favoriten sind jetzt teilbar");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Freigabe konnte nicht aktiviert werden");
    } finally {
      setBusy(false);
    }
  };

  const setListVisible = async (enabled: boolean) => {
    setBusy(true);
    try {
      await setFavoriteShareEnabled(enabled);
      await refresh();
      toast.success(enabled ? "Favoritenliste ist wieder sichtbar" : "Favoritenliste ist jetzt unsichtbar");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Einstellung konnte nicht gespeichert werden");
    } finally {
      setBusy(false);
    }
  };

  const setItemVisible = async (productId: string, visible: boolean) => {
    try {
      await setSharedFavoriteVisibility(productId, visible);
      await refresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Sichtbarkeit konnte nicht gespeichert werden");
    }
  };

  const copy = async () => {
    if (!share) return;
    await navigator.clipboard.writeText(favoriteShareUrl(share.token));
    toast.success("Favoriten-Link kopiert");
  };

  const nativeShare = async () => {
    if (!share) return;
    const url = favoriteShareUrl(share.token);
    if (navigator.share) await navigator.share({ title: "Meine Spareno-Favoriten", text: "Hier siehst du, was ich gerne mag.", url });
    else await copy();
  };

  const rotate = async () => {
    if (!window.confirm("Der bisherige Link funktioniert danach nicht mehr. Wirklich einen neuen Link erstellen?")) return;
    setBusy(true);
    try {
      await rotateFavoriteShare();
      await refresh();
      toast.success("Neuer Favoriten-Link erstellt");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Link konnte nicht erneuert werden");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHeader title="Favoriten teilen" subtitle="Du entscheidest, was Freunde sehen" />
      <div className="px-4 pt-3">
        <Link to="/favoriten" className="inline-flex h-9 items-center gap-1 rounded-xl border border-border bg-surface px-3 text-[11px] font-semibold text-navy">
          <ChevronLeft className="h-4 w-4" /> Zurück zu Favoriten
        </Link>
      </div>
      <div className="space-y-3 px-4 pt-3">
        {settings.isLoading && <div className="card-surface h-32 animate-pulse" />}

        {settings.data && !settings.data.enabledForAccount && (
          <section className="card-surface p-5 text-center">
            <span className="mx-auto grid h-11 w-11 place-items-center rounded-xl bg-primary-soft text-primary"><HeartHandshake className="h-5 w-5" /></span>
            <h2 className="mt-3 text-[15px] font-semibold text-navy">Favoriten sicher mit Freunden teilen</h2>
            <p className="mx-auto mt-1 max-w-[310px] text-[11px] leading-relaxed text-muted-foreground">Dafür brauchst du einen Spareno-Account. Standort, E-Mail, Märkte und Einkaufsliste werden niemals über den Favoriten-Link freigegeben.</p>
            <Link to="/auth" className="mt-4 inline-flex h-11 items-center gap-2 rounded-xl bg-primary px-4 text-[12px] font-semibold text-primary-foreground"><LogIn className="h-4 w-4" /> Anmelden oder registrieren</Link>
          </section>
        )}

        {settings.data?.enabledForAccount && !share && (
          <section className="card-surface p-5 text-center">
            <span className="mx-auto grid h-11 w-11 place-items-center rounded-xl bg-primary-soft text-primary"><Share2 className="h-5 w-5" /></span>
            <h2 className="mt-3 text-[15px] font-semibold text-navy">Deine Lieblingsprodukte, nur wenn du es willst</h2>
            <p className="mx-auto mt-1 max-w-[315px] text-[11px] leading-relaxed text-muted-foreground">Erstelle einen privaten, nicht erratbaren Link. Danach kannst du jeden einzelnen Favoriten sichtbar oder unsichtbar schalten.</p>
            <button type="button" disabled={busy} onClick={() => void enableSharing()} className="mt-4 h-11 rounded-xl bg-primary px-4 text-[12px] font-semibold text-primary-foreground disabled:opacity-50">Favoriten-Freigabe erstellen</button>
          </section>
        )}

        {share && (
          <>
            <section className="card-surface p-4">
              <div className="flex items-center gap-3">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-primary-soft text-primary">{share.enabled ? <Eye className="h-5 w-5" /> : <EyeOff className="h-5 w-5" />}</span>
                <div className="min-w-0 flex-1">
                  <h2 className="text-[13px] font-semibold text-navy">Gesamte Favoritenliste</h2>
                  <p className="mt-0.5 text-[10px] leading-relaxed text-muted-foreground">{share.enabled ? `${share.visibleCount} Favoriten sind über deinen Link sichtbar.` : "Deine Freunde bleiben verknüpft, sehen aktuell aber keine Favoriten."}</p>
                </div>
                <Toggle checked={share.enabled} onChange={(next) => void setListVisible(next)} label="Favoritenliste sichtbar" />
              </div>
            </section>

            <section className="card-surface p-4">
              <div className="flex items-center gap-2"><QrCode className="h-4 w-4 text-primary" /><h2 className="text-[13px] font-semibold text-navy">Link & QR-Code</h2></div>
              <div className="mt-3 flex items-center gap-3">
                <div className="grid h-28 w-28 shrink-0 place-items-center overflow-hidden rounded-xl border border-border bg-white p-2">
                  <img src={favoriteShareQrUrl(share.token)} alt="QR-Code zu deinen freigegebenen Favoriten" className="h-full w-full" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="break-all text-[9px] leading-relaxed text-muted-foreground">{favoriteShareUrl(share.token)}</p>
                  <div className="mt-2 flex gap-2">
                    <button type="button" onClick={() => void copy()} className="grid h-10 w-10 place-items-center rounded-xl border border-border text-navy" aria-label="Link kopieren"><Copy className="h-4 w-4" /></button>
                    <button type="button" onClick={() => void nativeShare()} className="flex h-10 flex-1 items-center justify-center gap-1.5 rounded-xl bg-primary text-[11px] font-semibold text-primary-foreground"><Share2 className="h-4 w-4" /> Teilen</button>
                  </div>
                </div>
              </div>
              <button type="button" disabled={busy} onClick={() => void rotate()} className="mt-3 inline-flex items-center gap-1.5 text-[10px] font-semibold text-muted-foreground"><RefreshCw className="h-3.5 w-3.5" /> Alten Link sperren & neuen erstellen</button>
            </section>

            <section>
              <div className="mb-2 flex items-center justify-between"><h2 className="text-[13px] font-semibold text-navy">Sichtbare Favoriten</h2><span className="text-[10px] text-muted-foreground">Einzeln steuerbar</span></div>
              <div className="card-surface divide-y divide-border">
                {share.items.length === 0 && <p className="px-4 py-5 text-[11px] text-muted-foreground">Du hast noch keine Produktfavoriten gespeichert.</p>}
                {share.items.map((item) => (
                  <div key={item.productId} className="flex items-center gap-3 px-3 py-3">
                    <div className="grid h-11 w-11 shrink-0 place-items-center overflow-hidden rounded-xl bg-muted-surface">
                      {item.product?.imageUrl ? <img src={item.product.imageUrl} alt="" className="h-full w-full object-contain p-1" /> : <HeartHandshake className="h-4 w-4 text-primary" />}
                    </div>
                    <div className="min-w-0 flex-1"><p className="line-clamp-2 text-[11px] font-semibold leading-snug text-navy">{item.product?.name ?? "Favorit"}</p><p className="mt-0.5 text-[9px] text-muted-foreground">{item.visible ? "Für Freunde sichtbar" : "Privat"}</p></div>
                    <button type="button" onClick={() => void setItemVisible(item.productId, !item.visible)} className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl ${item.visible ? "bg-primary-soft text-primary" : "bg-muted-surface text-muted-foreground"}`} aria-label={item.visible ? "Favorit verbergen" : "Favorit sichtbar machen"}>{item.visible ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}</button>
                  </div>
                ))}
              </div>
            </section>

            <section className="flex gap-2 rounded-xl border border-border bg-muted-surface/55 p-3">
              <LockKeyhole className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
              <p className="text-[10px] leading-relaxed text-muted-foreground">Geteilt werden ausschließlich deine Produktfavoriten, niemals Artikel aus deiner Einkaufsliste. Über den Link erscheinen nur dein Anzeigename und die von dir freigegebenen Favoriten. E-Mail, Standort, Lieblingsmärkte und Suchradius bleiben privat.</p>
            </section>
          </>
        )}
      </div>
    </div>
  );
}

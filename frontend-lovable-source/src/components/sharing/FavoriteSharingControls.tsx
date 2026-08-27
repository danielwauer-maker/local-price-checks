import { Link } from "@tanstack/react-router";
import { BellRing, ChevronRight, HeartHandshake, Share2, Users } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { fetchFavoriteShareSettings, fetchFriendFavorites } from "@/services/sharing-api";

export function FavoriteSharingControls() {
  const settings = useQuery({ queryKey: ["favorite-share-settings"], queryFn: fetchFavoriteShareSettings });
  const friends = useQuery({ queryKey: ["friend-favorites"], queryFn: fetchFriendFavorites, refetchInterval: 30_000 });
  const alerts = friends.data?.alerts.length ?? 0;
  const friendCount = friends.data?.friends.length ?? 0;

  return (
    <div className="mt-2 grid grid-cols-2 gap-2">
      <Link to="/favoriten/freunde" className="relative flex min-w-0 items-center gap-2 rounded-xl border border-border bg-muted-surface/65 px-3 py-2.5">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-primary-soft text-primary"><Users className="h-4 w-4" /></span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[11px] font-semibold text-navy">Von Freunden</p>
          <p className="truncate text-[9px] text-muted-foreground">{friendCount ? `${friendCount} gespeichert` : "Noch niemand"}</p>
        </div>
        <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        {alerts > 0 && <span className="absolute -right-1 -top-1 grid h-5 min-w-5 place-items-center rounded-full bg-discount px-1 text-[9px] font-bold text-white">{alerts}</span>}
      </Link>

      <Link to="/favoriten/teilen" className="flex min-w-0 items-center gap-2 rounded-xl border border-border bg-muted-surface/65 px-3 py-2.5">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-primary-soft text-primary">
          {settings.data?.share?.enabled ? <HeartHandshake className="h-4 w-4" /> : <Share2 className="h-4 w-4" />}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[11px] font-semibold text-navy">Favoriten teilen</p>
          <p className="truncate text-[9px] text-muted-foreground">{settings.data?.share?.enabled ? `${settings.data.share.visibleCount} sichtbar` : "Link & QR-Code"}</p>
        </div>
        <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      </Link>
    </div>
  );
}

export function FriendFavoriteAlerts() {
  const overview = useQuery({ queryKey: ["friend-favorites"], queryFn: fetchFriendFavorites, refetchInterval: 30_000 });
  const alerts = overview.data?.alerts ?? [];
  if (!overview.data?.enabled || alerts.length === 0) return null;
  const alert = alerts[0];

  return (
    <Link to="/favoriten/freunde" className="mt-2.5 flex items-center gap-2.5 rounded-xl border border-discount/15 bg-discount/[0.055] px-3 py-2.5">
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-surface text-discount shadow-sm"><BellRing className="h-4 w-4" /></span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[10px] font-semibold text-discount">Favorit von {alert.friendName} im Angebot</p>
        <p className="truncate text-[11px] font-semibold text-navy">{alert.product?.name ?? "Lieblingsprodukt"} · {alert.price.toFixed(2).replace(".", ",")} €</p>
        {alerts.length > 1 && <p className="text-[9px] text-muted-foreground">+ {alerts.length - 1} weitere Treffer</p>}
      </div>
      <ChevronRight className="h-4 w-4 shrink-0 text-discount" />
    </Link>
  );
}

import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Heart, Plus, Store, X } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/AppShell";
import { Tabs } from "@/components/lokero/FilterChips";
import { AlternativeCard, FavoriteCard, PriceAlertCard } from "@/components/lokero/FavoriteCard";
import { MarketCard } from "@/components/lokero/MarketCard";
import { EmptyState, SkeletonList } from "@/components/lokero/States";
import { FriendFavoriteAlerts } from "@/components/sharing/FavoriteSharingControls";
import { useStore } from "@/lib/app-store";
import { fetchFavoriteMarkets, fetchFeatures, getProduct } from "@/services/lokero-api";
import { fetchCategories } from "@/services/lokero-categories-api";
import { FAVORITES_CHANGED_EVENT, fetchFavoriteAlternatives, fetchFavoritePreferences, persistFavoriteAlternativePreference } from "@/services/lokero-state-api";
import { fetchFavoriteFamilies, fetchProductFamilies, setFavoriteFamily, type ProductFamily } from "@/services/lokero-personalization-api";
import type { Chain } from "@/data/lokero";

export const Route = createFileRoute("/favoriten")({
  head: () => ({ meta: [{ title: "Favoriten – Spareno" }] }),
  component: FavoritesScreen,
});

function FavoriteAlternativesBlock({ productId, enabled }: { productId: string; enabled: boolean }) {
  const alternatives = useQuery({
    queryKey: ["favorite-alternatives", productId],
    queryFn: () => fetchFavoriteAlternatives(productId),
    enabled,
    staleTime: 2 * 60_000,
  });
  if (!enabled || alternatives.isLoading || !alternatives.data?.length) return null;
  return (
    <div>
      <p className="mx-3 mt-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Passende Alternativen</p>
      <div className="mt-1 space-y-1">
        {alternatives.data.map((alternative) => <AlternativeCard key={alternative.product.id} product={alternative.product} price={alternative.price} kind={alternative.kind ?? "aehnlich"} reason={alternative.reason} market={alternative.market ? { ...alternative.market, chain: alternative.market.chain as Chain } : undefined} />)}
      </div>
    </div>
  );
}

function FavoritesScreen() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState("produkte");
  const [familyPickerOpen, setFamilyPickerOpen] = useState(false);
  const [preferenceOverrides, setPreferenceOverrides] = useState<Record<string, boolean>>({});
  const [familyOverrides, setFamilyOverrides] = useState<Record<string, boolean>>({});
  const { favoriteProducts, favoriteMarkets, toggleFavoriteProduct, toggleFavoriteMarket, alerts, setAlert } = useStore();

  const features = useQuery({ queryKey: ["lokero-features"], queryFn: fetchFeatures, staleTime: 5 * 60_000 });
  const markets = useQuery({ queryKey: ["favorite-markets"], queryFn: fetchFavoriteMarkets, staleTime: 60_000 });
  const preferences = useQuery({ queryKey: ["favorite-preferences"], queryFn: fetchFavoritePreferences, staleTime: 60_000 });
  const categories = useQuery({ queryKey: ["lokero-categories"], queryFn: fetchCategories, staleTime: 10 * 60_000 });
  const families = useQuery({ queryKey: ["product-families"], queryFn: fetchProductFamilies, staleTime: 10 * 60_000 });
  const favoriteFamilies = useQuery({ queryKey: ["favorite-families"], queryFn: fetchFavoriteFamilies, staleTime: 60_000 });
  const priceAlertsEnabled = features.data?.features.price_alerts === true;
  const tabs = [{ id: "produkte", label: "Produkte" }, { id: "maerkte", label: "Märkte" }, ...(priceAlertsEnabled ? [{ id: "alarm", label: "Preisalarm" }] : [])];

  useEffect(() => {
    const refresh = () => {
      void queryClient.invalidateQueries({ queryKey: ["favorite-preferences"] });
      void queryClient.invalidateQueries({ queryKey: ["favorite-families"] });
      void queryClient.invalidateQueries({ queryKey: ["favorite-matched-offers"] });
    };
    window.addEventListener(FAVORITES_CHANGED_EVENT, refresh);
    return () => window.removeEventListener(FAVORITES_CHANGED_EVENT, refresh);
  }, [queryClient]);

  const preferenceMap = useMemo(() => Object.fromEntries((preferences.data ?? []).map((row) => [row.productId, row.allowAlternatives])), [preferences.data]);
  const rows = useMemo(() => favoriteProducts.map((productId) => ({ productId })), [favoriteProducts]);
  const grouped = useMemo(() => (categories.data ?? []).map((category) => ({ category, rows: rows.filter((row) => getProduct(row.productId)?.category === category.id) })).filter((group) => group.rows.length > 0), [categories.data, rows]);

  const serverFamilyMap = useMemo(() => new Map((favoriteFamilies.data ?? []).map((family) => [family.slug, family])), [favoriteFamilies.data]);
  const activeFamilySlugs = useMemo(() => {
    const slugs = new Set(serverFamilyMap.keys());
    for (const [slug, active] of Object.entries(familyOverrides)) {
      if (active) slugs.add(slug); else slugs.delete(slug);
    }
    return slugs;
  }, [serverFamilyMap, familyOverrides]);
  const activeFamilies = useMemo(() => {
    const allBySlug = new Map<string, ProductFamily>((families.data ?? []).map((family) => [family.slug, family]));
    for (const family of favoriteFamilies.data ?? []) allBySlug.set(family.slug, family);
    return Array.from(activeFamilySlugs).map((slug) => allBySlug.get(slug)).filter((family): family is ProductFamily => Boolean(family));
  }, [families.data, favoriteFamilies.data, activeFamilySlugs]);

  const changeAlternativePreference = async (productId: string, next: boolean) => {
    const previous = preferenceOverrides[productId] ?? preferenceMap[productId] ?? false;
    setPreferenceOverrides((current) => ({ ...current, [productId]: next }));
    queryClient.setQueryData(["favorite-preferences"], (current: Array<{ productId: string; allowAlternatives: boolean }> | undefined) => {
      const rows = current ?? [];
      const existing = rows.some((row) => row.productId === productId);
      return existing ? rows.map((row) => row.productId === productId ? { ...row, allowAlternatives: next } : row) : [...rows, { productId, allowAlternatives: next }];
    });
    const ok = await persistFavoriteAlternativePreference(productId, next);
    if (!ok) {
      setPreferenceOverrides((current) => ({ ...current, [productId]: previous }));
      queryClient.setQueryData(["favorite-preferences"], (current: Array<{ productId: string; allowAlternatives: boolean }> | undefined) => (current ?? []).map((row) => row.productId === productId ? { ...row, allowAlternatives: previous } : row));
      toast.error("Einstellung konnte nicht gespeichert werden");
      return;
    }
    setPreferenceOverrides((current) => { const copy = { ...current }; delete copy[productId]; return copy; });
  };

  const toggleFamily = async (slug: string, next: boolean) => {
    const previous = activeFamilySlugs.has(slug);
    setFamilyOverrides((current) => ({ ...current, [slug]: next }));
    const ok = await setFavoriteFamily(slug, next);
    if (!ok) { setFamilyOverrides((current) => ({ ...current, [slug]: previous })); toast.error("Produktfamilie konnte nicht gespeichert werden"); return; }
    queryClient.setQueryData<ProductFamily[]>(["favorite-families"], (current = []) => {
      if (!next) return current.filter((family) => family.slug !== slug);
      const family = (families.data ?? []).find((item) => item.slug === slug);
      return family && !current.some((item) => item.slug === slug) ? [...current, family] : current;
    });
    setFamilyOverrides((current) => { const copy = { ...current }; delete copy[slug]; return copy; });
  };

  return (
    <div>
      <PageHeader title="Favoriten" />
      <div className="bg-surface px-4 pb-3"><FriendFavoriteAlerts /></div>
      <div className="bg-surface px-4"><Tabs options={tabs} value={tab === "alarm" && !priceAlertsEnabled ? "produkte" : tab} onChange={setTab} /></div>
      <div className="px-4 pt-4">
        {tab === "produkte" && (
          <section className="space-y-5">
            <div>
              <div className="mb-2.5 flex items-center justify-between"><h2 className="text-[13px] font-semibold text-navy">Produktfamilien</h2><button type="button" onClick={() => setFamilyPickerOpen(true)} className="inline-flex items-center gap-1 text-[12px] font-semibold text-primary"><Plus className="h-3.5 w-3.5" /> Hinzufügen</button></div>
              {activeFamilies.length > 0 ? <div className="flex flex-wrap gap-2">{activeFamilies.map((family) => <button key={family.slug} type="button" onClick={() => void toggleFamily(family.slug, false)} className="inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-2 text-[12px] font-medium text-navy">{family.label}<Heart className="h-3.5 w-3.5 fill-discount text-discount" /></button>)}</div> : <p className="text-[11px] text-muted-foreground">Merke dir z. B. Bier, Cola oder Fisch und erhalte passende Angebote unabhängig von der Marke.</p>}
            </div>
            <div>
              <h2 className="mb-2.5 text-[13px] font-semibold text-navy">Deine Produktfavoriten</h2>
              {categories.isLoading && <SkeletonList count={3} />}
              {!categories.isLoading && rows.length === 0 && <EmptyState icon={Heart} title="Noch keine Favoriten" description="Merke dir Produkte, die du regelmäßig kaufst." action={<Link to="/angebote" className="inline-flex h-11 items-center rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground">Produkte entdecken</Link>} />}
              <div className="space-y-5">{grouped.map(({ category, rows: categoryRows }) => <div key={category.id}><div className="mb-2 flex items-center justify-between"><h3 className="text-[12px] font-semibold text-navy">{category.label}</h3><span className="text-[10px] text-muted-foreground">{categoryRows.length}</span></div><div className="space-y-3">{categoryRows.map((f) => { const product = getProduct(f.productId); if (!product) return null; const allowAlternatives = preferenceOverrides[f.productId] ?? preferenceMap[f.productId] ?? false; return <div key={f.productId}><FavoriteCard product={product} isFavorite onToggleFavorite={() => toggleFavoriteProduct(f.productId)} allowAlternatives={allowAlternatives} onToggleAlternatives={(next) => void changeAlternativePreference(f.productId, next)} /><FavoriteAlternativesBlock productId={f.productId} enabled={allowAlternatives} /></div>; })}</div></div>)}</div>
            </div>
          </section>
        )}
        {tab === "maerkte" && <section className="space-y-2.5">{markets.isLoading && <SkeletonList count={2} />}{markets.isSuccess && favoriteMarkets.length === 0 && <EmptyState icon={Store} title="Noch keine Lieblingsmärkte" description="Markiere Märkte, damit Spareno deine Einkäufe darauf abstimmt." />}{(markets.data ?? []).filter((m) => favoriteMarkets.includes(m.id)).map((m) => <MarketCard key={m.id} market={m} isFavorite onToggleFavorite={() => toggleFavoriteMarket(m.id)} />)}</section>}
        {priceAlertsEnabled && tab === "alarm" && <section className="space-y-3">{Object.entries(alerts).map(([productId, a]) => { const product = getProduct(productId); if (!product) return null; return <div key={productId}><FavoriteCard product={product} isFavorite={favoriteProducts.includes(productId)} onToggleFavorite={() => toggleFavoriteProduct(productId)} /><PriceAlertCard targetPrice={a.targetPrice} active={a.active} onToggle={() => setAlert(productId, a.targetPrice, !a.active)} /></div>; })}</section>}
      </div>
      {familyPickerOpen && <div className="fixed inset-0 z-50 flex items-end bg-navy/30" onClick={() => setFamilyPickerOpen(false)}><div role="dialog" aria-modal="true" aria-labelledby="family-picker-title" className="w-full rounded-t-3xl bg-surface p-4 pb-[max(1rem,env(safe-area-inset-bottom))]" onClick={(event) => event.stopPropagation()}><div className="mb-3 flex items-center justify-between"><div><h2 id="family-picker-title" className="text-[16px] font-semibold text-navy">Produktfamilie hinzufügen</h2><p className="text-[11px] text-muted-foreground">Du bekommst alle passenden lokalen Angebote dieser Produktart.</p></div><button type="button" aria-label="Produktfamilie schließen" onClick={() => setFamilyPickerOpen(false)} className="grid h-9 w-9 place-items-center"><X className="h-5 w-5" /></button></div><div className="grid grid-cols-2 gap-2">{(families.data ?? []).map((family) => { const active = activeFamilySlugs.has(family.slug); return <button key={family.slug} type="button" onClick={() => void toggleFamily(family.slug, !active)} className={`flex items-center justify-between rounded-xl border px-3 py-3 text-left text-[12px] font-medium ${active ? "border-discount bg-surface text-navy" : "border-border bg-muted-surface text-navy"}`}><span>{family.label}</span><Heart className={`h-4 w-4 text-discount ${active ? "fill-discount" : ""}`} /></button>; })}</div></div></div>}
    </div>
  );
}

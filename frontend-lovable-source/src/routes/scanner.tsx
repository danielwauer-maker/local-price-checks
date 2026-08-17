import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { Camera, Keyboard, Plus, X } from "lucide-react";
import { PageHeader } from "@/components/AppShell";
import { useActiveMarketIds, useStore } from "@/lib/app-store";
import {
  PRODUCTS,
  PRICES,
  effectivePrice,
  formatEuro,
  getMarket,
  type Product,
} from "@/data/demo";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

export const Route = createFileRoute("/scanner")({
  head: () => ({
    meta: [
      { title: "Barcode scannen & Preise vergleichen – LocalPrices" },
      { name: "description", content: "Scanne den Barcode eines Produkts und sieh sofort, welcher Markt in deinem Umkreis den besten Preis hat." },
      { property: "og:title", content: "Barcode-Scanner – LocalPrices" },
      { property: "og:description", content: "Produkt scannen und Preise aller Märkte im Umkreis vergleichen." },
    ],
  }),
  component: ScannerPage,
});

type Detector = { detect: (source: HTMLVideoElement) => Promise<Array<{ rawValue: string }>> };

function ScannerPage() {
  const activeIds = useActiveMarketIds();
  const { addToBasket } = useStore();
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [scanning, setScanning] = useState(false);
  const [manual, setManual] = useState("");
  const [found, setFound] = useState<Product | null>(null);

  useEffect(() => () => streamRef.current?.getTracks().forEach((t) => t.stop()), []);

  function resolve(ean: string) {
    const product = PRODUCTS.find((p) => p.ean === ean.trim());
    if (product) {
      setFound(product);
      toast.success(`${product.name} erkannt`);
    } else {
      toast.error("Produkt nicht in der Datenbank");
    }
  }

  async function startCamera() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
      streamRef.current = stream;
      setScanning(true);
      requestAnimationFrame(async () => {
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play().catch(() => undefined);
        }
      });
      const Ctor = (window as unknown as { BarcodeDetector?: new (o: object) => Detector }).BarcodeDetector;
      if (!Ctor) {
        toast("Barcode-Erkennung wird von diesem Browser nicht unterstützt – Code eingeben.");
        return;
      }
      const detector = new Ctor({ formats: ["ean_13", "ean_8", "upc_a"] });
      const tick = async () => {
        if (!videoRef.current || !streamRef.current) return;
        try {
          const codes = await detector.detect(videoRef.current);
          if (codes[0]) {
            resolve(codes[0].rawValue);
            stopCamera();
            return;
          }
        } catch { /* frame */ }
        setTimeout(tick, 400);
      };
      tick();
    } catch {
      toast.error("Kamerazugriff nicht möglich.");
    }
  }

  function stopCamera() {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setScanning(false);
  }

  const comparison = found
    ? activeIds
        .map((id) => {
          const price = PRICES.find((p) => p.productId === found.id && p.marketId === id);
          const market = getMarket(id);
          return price && market ? { market, price, value: effectivePrice(price) } : null;
        })
        .filter((x): x is NonNullable<typeof x> => Boolean(x))
        .sort((a, b) => a.value - b.value)
    : [];

  return (
    <div>
      <PageHeader title="Scanner" subtitle="Barcode scannen und sofort vergleichen" />
      <div className="mx-5 overflow-hidden rounded-3xl bg-foreground/90 shadow-float">
        <div className="relative aspect-[4/3]">
          {scanning ? <video ref={videoRef} muted playsInline className="h-full w-full object-cover" /> : (
            <div className="flex h-full flex-col items-center justify-center gap-3 text-background/80">
              <Camera className="h-9 w-9" /><p className="text-sm">Kamera starten, um zu scannen</p>
            </div>
          )}
          <div className="pointer-events-none absolute inset-8 rounded-2xl border-2 border-accent/70" />
          {scanning && <button onClick={stopCamera} className="absolute right-3 top-3 rounded-full bg-background/90 p-2" aria-label="Scan beenden"><X className="h-4 w-4" /></button>}
        </div>
        <button onClick={scanning ? stopCamera : startCamera} className="w-full bg-primary py-3.5 text-sm font-semibold text-primary-foreground">{scanning ? "Scan beenden" : "Kamera starten"}</button>
      </div>

      <div className="mx-5 mt-4 flex items-center gap-2 rounded-2xl bg-surface px-4 py-3 shadow-card">
        <Keyboard className="h-4 w-4 text-muted-foreground" />
        <input value={manual} inputMode="numeric" onChange={(e) => setManual(e.target.value)} onKeyDown={(e) => e.key === "Enter" && resolve(manual)} placeholder="EAN manuell eingeben" className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground" />
        <button onClick={() => resolve(manual)} className="rounded-full bg-secondary px-3 py-1.5 text-xs font-semibold text-secondary-foreground">prüfen</button>
      </div>

      <div className="no-scrollbar mt-3 flex gap-2 overflow-x-auto px-5">
        {PRODUCTS.filter((p) => p.ean).slice(0, 6).map((p) => <button key={p.id} onClick={() => resolve(p.ean)} className="shrink-0 rounded-full bg-surface px-3 py-1.5 text-xs text-muted-foreground shadow-card">{p.emoji} {p.name.split(" ")[0]}</button>)}
      </div>

      {found && <section className="mx-5 mt-5 surface-card overflow-hidden">
        <header className="flex items-center gap-3 border-b border-border p-4">
          <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-surface-2 text-2xl">{found.emoji}</span>
          <div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold">{found.name}</p><p className="text-xs text-muted-foreground">{found.brand} · {found.unit}</p></div>
          <button onClick={() => { addToBasket(found.id); toast.success("Zur Liste hinzugefügt"); }} className="rounded-full bg-primary p-2.5 text-primary-foreground" aria-label="Zur Liste"><Plus className="h-4 w-4" strokeWidth={2.6} /></button>
        </header>
        <ul>{comparison.map((c, i) => <li key={c.market.id} className="flex items-center gap-3 border-b border-border px-4 py-3 last:border-0">
          <span className={cn("flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-bold", i === 0 ? "bg-primary text-primary-foreground" : "bg-secondary text-secondary-foreground")}>{i + 1}</span>
          <span className="min-w-0 flex-1 truncate text-sm">{c.market.name}</span>
          {c.price.offer && <span className="rounded-full bg-deal/12 px-2 py-0.5 text-[10px] font-bold text-deal">Angebot</span>}
          <span className={cn("tabular text-sm font-semibold", i === 0 && "text-primary")}>{formatEuro(c.value)}</span>
        </li>)}</ul>
      </section>}
    </div>
  );
}

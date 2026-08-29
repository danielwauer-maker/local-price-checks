import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { Camera, Keyboard, Plus, X } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/AppShell";
import { ProductThumb } from "@/components/lokero/CategoryIcon";
import { MarketLogo } from "@/components/lokero/MarketLogo";
import { DiscountBadge } from "@/components/lokero/DiscountBadge";
import { useStore } from "@/lib/app-store";
import { PRODUCTS, type Product } from "@/data/lokero";
import { getMarket, getOfferFor, marketPricesFor } from "@/services/lokero-api";
import { formatEuro, formatKm } from "@/lib/format";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/scanner")({
  head: () => ({
    meta: [
      { title: "Barcode scannen & Preise vergleichen – Spareno" },
      {
        name: "description",
        content:
          "Scanne den Barcode eines Produkts und sieh sofort, welcher Markt in deiner Nähe den besten Preis hat.",
      },
      { property: "og:title", content: "Barcode-Scanner – Spareno" },
      {
        property: "og:description",
        content: "Produkt scannen und Preise aller Märkte in deiner Nähe vergleichen.",
      },
    ],
  }),
  component: ScannerScreen,
});

type Detector = { detect: (source: HTMLVideoElement) => Promise<Array<{ rawValue: string }>> };

function ScannerScreen() {
  const navigate = useNavigate();
  const { addToList } = useStore();
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [scanning, setScanning] = useState(false);
  const [manual, setManual] = useState("");
  const [found, setFound] = useState<Product | null>(null);

  useEffect(() => {
    return () => streamRef.current?.getTracks().forEach((t) => t.stop());
  }, []);

  function stop() {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setScanning(false);
  }

  function resolve(ean: string) {
    const product = PRODUCTS.find((p) => p.ean === ean.trim());
    if (product) {
      setFound(product);
      stop();
      toast.success(`${product.name} erkannt`);
    } else {
      toast.error("Produkt nicht in der Datenbank");
    }
  }

  async function start() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment" },
      });
      streamRef.current = stream;
      setScanning(true);
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      const Ctor = (window as unknown as { BarcodeDetector?: new (o: unknown) => Detector })
        .BarcodeDetector;
      if (!Ctor) {
        toast.info("Dein Browser unterstützt keinen Scanner – bitte EAN eingeben.");
        return;
      }
      const detector = new Ctor({ formats: ["ean_13", "ean_8", "code_128"] });
      const tick = async () => {
        if (!videoRef.current || !streamRef.current) return;
        try {
          const codes = await detector.detect(videoRef.current);
          if (codes[0]) {
            resolve(codes[0].rawValue);
            return;
          }
        } catch {
          /* ignorieren, nächster Frame */
        }
        requestAnimationFrame(() => void tick());
      };
      void tick();
    } catch {
      toast.error("Kamerazugriff nicht möglich");
      setScanning(false);
    }
  }

  const offer = found ? getOfferFor(found.id) : undefined;
  const prices = found ? marketPricesFor(found.id) : [];

  return (
    <div className="pb-4">
      <PageHeader title="Scanner" subtitle="Barcode scannen und Preise vergleichen" />

      <div className="px-4">
        <div className="relative aspect-[4/5] overflow-hidden rounded-2xl bg-navy">
          <video
            ref={videoRef}
            playsInline
            muted
            className={cn("h-full w-full object-cover", !scanning && "opacity-0")}
          />
          {!scanning && (
            <div className="absolute inset-0 grid place-items-center gap-3 p-6 text-center">
              <Camera className="mx-auto h-9 w-9 text-primary" />
              <p className="text-[13px] text-white/80">
                Richte die Kamera auf den Barcode des Produkts.
              </p>
              <button
                onClick={() => void start()}
                className="mx-auto inline-flex h-12 items-center rounded-xl bg-primary px-5 text-sm font-semibold text-primary-foreground"
              >
                Scanner starten
              </button>
            </div>
          )}
          {scanning && (
            <>
              <div className="pointer-events-none absolute inset-x-8 top-1/2 h-40 -translate-y-1/2 rounded-2xl border-2 border-primary/80" />
              <button
                onClick={stop}
                aria-label="Scanner stoppen"
                className="absolute right-3 top-3 grid h-10 w-10 place-items-center rounded-full bg-navy/70 text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </>
          )}
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            resolve(manual);
          }}
          className="mt-3 flex items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2"
        >
          <Keyboard className="h-4 w-4 shrink-0 text-muted-foreground" />
          <input
            value={manual}
            onChange={(e) => setManual(e.target.value)}
            inputMode="numeric"
            placeholder="EAN manuell eingeben"
            className="tabular min-w-0 flex-1 bg-transparent text-[13px] outline-none placeholder:text-muted-foreground"
          />
          <button
            type="submit"
            className="shrink-0 rounded-lg bg-primary px-3 py-1.5 text-[12px] font-semibold text-primary-foreground"
          >
            Prüfen
          </button>
        </form>
      </div>

      {found && (
        <section className="mt-4 px-4">
          <div className="card-surface p-4">
            <div className="flex items-center gap-3">
              <ProductThumb categoryId={found.category} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[14px] font-semibold text-navy">{found.name}</p>
                <p className="truncate text-[11px] text-muted-foreground">
                  {found.brand} · {found.amount}
                </p>
              </div>
              {offer?.discount != null && <DiscountBadge value={offer.discount} />}
            </div>

            <div className="mt-3 divide-y divide-border border-t border-border">
              {prices.map((p) => {
                const m = getMarket(p.marketId);
                if (!m) return null;
                return (
                  <div key={p.marketId} className="flex items-center gap-3 py-2.5">
                    <MarketLogo chain={m.chain} size="sm" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[12px] font-medium text-navy">{m.name}</p>
                      <p className="tabular text-[11px] text-muted-foreground">
                        {formatKm(m.distanceKm)}
                      </p>
                    </div>
                    <span className="tabular text-[13px] font-semibold text-navy">
                      {formatEuro(p.price)}
                    </span>
                  </div>
                );
              })}
            </div>

            <div className="mt-3 grid grid-cols-2 gap-2">
              <button
                onClick={() => {
                  addToList(found.id);
                  toast.success(`${found.name} auf deiner Liste`);
                }}
                className="flex h-11 items-center justify-center gap-2 rounded-xl bg-primary text-[13px] font-semibold text-primary-foreground"
              >
                <Plus className="h-4 w-4" /> Auf die Liste
              </button>
              <button
                onClick={() => navigate({ to: "/produkt/$productId", params: { productId: found.id } })}
                className="h-11 rounded-xl border border-border bg-surface text-[13px] font-semibold text-navy"
              >
                Details
              </button>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}

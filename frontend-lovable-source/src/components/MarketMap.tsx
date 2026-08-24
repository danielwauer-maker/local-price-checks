import { useEffect } from "react";
import { Circle, MapContainer, Marker, TileLayer, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { Market } from "@/data/lokero";

type Props = {
  center: { lat: number; lng: number };
  radiusKm: number;
  markets: Market[];
  activeId?: string | null;
  onSelect?: (id: string) => void;
};

const CHAIN_COLORS: Record<string, { bg: string; fg: string; label: string }> = {
  REWE: { bg: "#D8232A", fg: "#ffffff", label: "REWE" },
  Lidl: { bg: "#0050AA", fg: "#FFF000", label: "Lidl" },
  "ALDI SÜD": { bg: "#00005F", fg: "#FF7300", label: "ALDI" },
  Netto: { bg: "#FFE500", fg: "#D30032", label: "Netto" },
  EDEKA: { bg: "#003C7D", fg: "#FFDD00", label: "EDEKA" },
};

function markerIcon(chain: string, active: boolean) {
  const c = CHAIN_COLORS[chain] ?? { bg: "#0F172A", fg: "#fff", label: chain };
  const w = active ? 42 : 36;
  return L.divIcon({
    className: "",
    html: `<div style="
      display:flex;align-items:center;justify-content:center;
      width:${w}px;height:22px;border-radius:6px;
      font:700 9px/1 Sora,sans-serif;letter-spacing:-0.2px;
      color:${c.fg};background:${c.bg};
      border:2px solid #fff;box-shadow:0 2px 8px rgba(15,23,42,.28);
    ">${c.label}</div>`,
    iconSize: [w, 22],
    iconAnchor: [w / 2, 11],
  });
}

function userIcon() {
  return L.divIcon({
    className: "",
    html: `<div style="width:14px;height:14px;border-radius:999px;background:#3B82F6;border:3px solid #fff;box-shadow:0 0 0 5px rgba(59,130,246,.18)"></div>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
}

function Recenter({ center, radiusKm }: { center: { lat: number; lng: number }; radiusKm: number }) {
  const map = useMap();
  useEffect(() => {
    const zoom = radiusKm <= 5 ? 12 : radiusKm <= 10 ? 11.5 : radiusKm <= 15 ? 11 : 10;
    map.setView([center.lat, center.lng], zoom, { animate: true });
  }, [center.lat, center.lng, radiusKm, map]);
  return null;
}

export default function MarketMap({ center, radiusKm, markets, activeId, onSelect }: Props) {
  return (
    <MapContainer
      center={[center.lat, center.lng]}
      zoom={11}
      zoomControl={false}
      scrollWheelZoom={false}
      style={{ height: "100%", width: "100%" }}
    >
      <TileLayer
        url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
        attribution="&copy; OpenStreetMap, &copy; CARTO"
      />
      <Recenter center={center} radiusKm={radiusKm} />
      <Circle
        center={[center.lat, center.lng]}
        radius={radiusKm * 1000}
        pathOptions={{ color: "#22C55E", weight: 1.5, fillColor: "#22C55E", fillOpacity: 0.06 }}
      />
      <Marker position={[center.lat, center.lng]} icon={userIcon()} />
      {markets.map((m) => (
        <Marker
          key={m.id}
          position={[m.lat, m.lng]}
          icon={markerIcon(m.chain, activeId === m.id)}
          eventHandlers={{ click: () => onSelect?.(m.id) }}
        />
      ))}
    </MapContainer>
  );
}

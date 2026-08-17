import { useEffect } from "react";
import { Circle, MapContainer, Marker, TileLayer, ZoomControl, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { Market } from "@/data/demo";

type Props = {
  center: { lat: number; lng: number };
  radiusKm: number;
  markets: Array<Market & { distance: number }>;
  selected: string[];
  onSelect: (id: string) => void;
  activeId?: string | null;
};

function markerIcon(label: string, active: boolean, chosen: boolean, logoUrl?: string) {
  const content = logoUrl
    ? `<img src="${logoUrl}" alt="${label}" style="width:72%;height:72%;object-fit:contain" />`
    : label;
  return L.divIcon({
    className: "",
    html: `<div style="
      display:flex;align-items:center;justify-content:center;
      width:${active ? 44 : 38}px;height:${active ? 44 : 38}px;border-radius:999px;
      font:600 10px/1.1 'Plus Jakarta Sans',sans-serif;text-align:center;
      color:${chosen ? "#fff" : "oklch(0.3 0.04 155)"};
      background:#fff;
      border:3px solid ${chosen ? "oklch(0.47 0.113 158)" : "oklch(0.9 0.01 130)"};
      box-shadow:0 6px 16px -6px rgba(20,50,35,.5);
      overflow:hidden;
    ">${content}</div>`,
    iconSize: [active ? 44 : 38, active ? 44 : 38],
    iconAnchor: [active ? 22 : 19, active ? 22 : 19],
  });
}

function userIcon() {
  return L.divIcon({
    className: "",
    html: `<div style="width:18px;height:18px;border-radius:999px;background:oklch(0.6 0.09 250);border:3px solid #fff;box-shadow:0 0 0 6px rgba(70,120,220,.18)"></div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });
}

function Recenter({ center, radiusKm }: { center: { lat: number; lng: number }; radiusKm: number }) {
  const map = useMap();
  useEffect(() => {
    const zoom = radiusKm <= 3 ? 13 : radiusKm <= 8 ? 12 : radiusKm <= 15 ? 11 : 10;
    map.setView([center.lat, center.lng], zoom, { animate: true });
  }, [center.lat, center.lng, radiusKm, map]);
  return null;
}

export default function MarketMap({ center, radiusKm, markets, selected, onSelect, activeId }: Props) {
  return (
    <MapContainer
      center={[center.lat, center.lng]}
      zoom={12}
      zoomControl={false}
      scrollWheelZoom
      style={{ height: "100%", width: "100%" }}
    >
      <ZoomControl position="bottomright" />
      <TileLayer
        url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
        attribution='&copy; OpenStreetMap, &copy; CARTO'
      />
      <Recenter center={center} radiusKm={radiusKm} />
      <Circle
        center={[center.lat, center.lng]}
        radius={radiusKm * 1000}
        pathOptions={{ color: "oklch(0.47 0.113 158)", weight: 1.5, fillColor: "oklch(0.47 0.113 158)", fillOpacity: 0.07 }}
      />
      <Marker position={[center.lat, center.lng]} icon={userIcon()} />
      {markets.map((m) => (
        <Marker
          key={m.id}
          position={[m.lat, m.lng]}
          icon={markerIcon(m.chain.split(" ")[0]!, activeId === m.id, selected.includes(m.id), (m as any).logoUrl)}
          eventHandlers={{ click: () => onSelect(m.id) }}
        />
      ))}
    </MapContainer>
  );
}

import { useEffect } from "react";
import { Circle, MapContainer, TileLayer, ZoomControl, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";

export type CoverageRegion = {
  id: number;
  name: string;
  postalCode?: string | null;
  city?: string | null;
  lat: number;
  lng: number;
  radiusKm: number;
  status: "live" | "building" | "paused" | string;
  active: boolean;
  stores: number;
  verifiedStores: number;
  currentOffers: number;
};

function FitRegions({ regions, fallback }: { regions: CoverageRegion[]; fallback: { lat: number; lng: number } }) {
  const map = useMap();
  useEffect(() => {
    if (!regions.length) {
      map.setView([fallback.lat, fallback.lng], 8);
      return;
    }
    const bounds = regions.map((region) => [region.lat, region.lng] as [number, number]);
    map.fitBounds(bounds, { padding: [24, 24], maxZoom: 10 });
  }, [regions, fallback.lat, fallback.lng, map]);
  return null;
}

export default function CoverageMap({ regions, center }: { regions: CoverageRegion[]; center: { lat: number; lng: number } }) {
  return (
    <MapContainer center={[center.lat, center.lng]} zoom={8} zoomControl={false} scrollWheelZoom={false} style={{ height: "100%", width: "100%" }}>
      <ZoomControl position="bottomright" />
      <TileLayer url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png" attribution='&copy; OpenStreetMap, &copy; CARTO' />
      <FitRegions regions={regions} fallback={center} />
      {regions.map((region) => (
        <Circle
          key={region.id}
          center={[region.lat, region.lng]}
          radius={region.radiusKm * 1000}
          pathOptions={region.status === "live"
            ? { color: "oklch(0.47 0.113 158)", weight: 2, fillColor: "oklch(0.47 0.113 158)", fillOpacity: 0.18 }
            : { color: "oklch(0.69 0.13 75)", weight: 2, dashArray: "6 5", fillColor: "oklch(0.82 0.10 85)", fillOpacity: 0.12 }}
        />
      ))}
    </MapContainer>
  );
}

// Leaflet map showing parish markers.
//
// Leaflet is fully imperative (it manipulates the DOM directly), so we
// use refs to hold the map and marker layer, then sync React state into
// Leaflet calls. The map tile layer uses OpenStreetMap directly — no API
// key, free, suitable for a v1. For production replace with a tile
// provider with a usage policy that fits (Mapbox, Stadia, Maptiler).
//
// Why not react-leaflet? It's a thin wrapper but adds a build dependency
// and an indirection that's not worth it for one map.

import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { useEffect, useRef } from "react";
import type { Parish } from "../api/types";

interface Props {
  parishes: Parish[];
  selectedId?: string | null;
  center?: { lat: number; lng: number };  // optional initial center
  onSelect: (parish: Parish) => void;
  className?: string;
}

// Workaround Leaflet's default icon paths breaking with Vite. Use inline
// SVG icons instead of the bundled PNGs.
const PARISH_ICON = L.divIcon({
  className: "parish-marker",
  html: `<svg width="28" height="36" viewBox="0 0 28 36" xmlns="http://www.w3.org/2000/svg">
    <path d="M14 0C6.27 0 0 6.27 0 14c0 10.5 14 22 14 22s14-11.5 14-22C28 6.27 21.73 0 14 0z" fill="#7c2d12"/>
    <circle cx="14" cy="14" r="6" fill="#fafaf9"/>
  </svg>`,
  iconSize: [28, 36],
  iconAnchor: [14, 36],
});

const SELECTED_ICON = L.divIcon({
  className: "parish-marker selected",
  html: `<svg width="36" height="46" viewBox="0 0 28 36" xmlns="http://www.w3.org/2000/svg">
    <path d="M14 0C6.27 0 0 6.27 0 14c0 10.5 14 22 14 22s14-11.5 14-22C28 6.27 21.73 0 14 0z" fill="#581c0c"/>
    <circle cx="14" cy="14" r="6" fill="#fff"/>
  </svg>`,
  iconSize: [36, 46],
  iconAnchor: [18, 46],
});

export function ParishMap({
  parishes,
  selectedId,
  center,
  onSelect,
  className,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const markersRef = useRef<L.Marker[]>([]);

  // Initial map setup — runs once.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, {
      zoomControl: true,
      attributionControl: true,
    }).setView([center?.lat ?? 40.7128, center?.lng ?? -74.006], center ? 12 : 4);

    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(map);

    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
    // We only want one map for the component's life; center+zoom changes
    // are applied separately below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sync markers whenever the parishes list changes.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    for (const m of markersRef.current) m.remove();
    markersRef.current = [];

    const points: L.LatLngTuple[] = [];
    for (const p of parishes) {
      if (p.latitude == null || p.longitude == null) continue;
      const marker = L.marker([p.latitude, p.longitude], {
        icon: p.id === selectedId ? SELECTED_ICON : PARISH_ICON,
      }).addTo(map);
      marker.on("click", () => onSelect(p));
      marker.bindTooltip(p.name, { direction: "top", offset: [0, -32] });
      markersRef.current.push(marker);
      points.push([p.latitude, p.longitude]);
    }

    // Fit bounds to all parishes, unless we have only one (then center on it).
    if (points.length > 1) {
      map.fitBounds(L.latLngBounds(points), { padding: [40, 40], maxZoom: 14 });
    } else if (points.length === 1) {
      map.setView(points[0], 13);
    }
  }, [parishes, selectedId, onSelect]);

  // Re-center when the caller passes a new center (e.g. user's geolocation
  // resolved). Don't override the user's manual panning otherwise.
  useEffect(() => {
    if (!mapRef.current || !center) return;
    mapRef.current.setView([center.lat, center.lng], 12);
  }, [center?.lat, center?.lng]);

  return <div ref={containerRef} className={className} />;
}

import { useEffect } from "react";
import { useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet.heat";

// Renders (or removes) a leaflet.heat layer for points of
// {lat, lon, intensity} where intensity is a risk score from 0 to 4.
export default function HeatLayer({ points }) {
  const map = useMap();

  useEffect(() => {
    if (!points || points.length === 0) return undefined;
    const heatPoints = points.map((p) => [p.lat, p.lon, Math.max(0.08, p.intensity / 4)]);
    const layer = L.heatLayer(heatPoints, {
      radius: 28,
      blur: 18,
      maxZoom: 10,
      minOpacity: 0.35,
      gradient: {
        0.0: "#22c55e",
        0.25: "#eab308",
        0.5: "#f97316",
        0.75: "#ef4444",
        1.0: "#111827",
      },
    });
    layer.addTo(map);
    return () => {
      map.removeLayer(layer);
    };
  }, [map, points]);

  return null;
}

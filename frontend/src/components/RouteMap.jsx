import { useEffect } from "react";
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, useMap } from "react-leaflet";

export const RISK_COLORS = {
  Low: "#22c55e",
  Moderate: "#eab308",
  High: "#f97316",
  Severe: "#ef4444",
  "No Travel": "#111827",
};

function FitBounds({ routes, selectedId }) {
  const map = useMap();
  useEffect(() => {
    if (!routes || routes.length === 0) return;
    const selected = routes.find((r) => r.id === selectedId) || routes[0];
    const latLngs = selected.geometry.map(([lon, lat]) => [lat, lon]);
    if (latLngs.length > 0) {
      map.fitBounds(latLngs, { padding: [40, 40] });
    }
  }, [map, routes, selectedId]);
  return null;
}

function formatEta(iso) {
  const d = new Date(iso);
  return d.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function RouteMap({ routes, selectedId, onSelect, heatPoints }) {
  const center = [39.5, -98.35];
  return (
    <MapContainer center={center} zoom={4} className="map" scrollWheelZoom>
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {routes && <FitBounds routes={routes} selectedId={selectedId} />}
      {routes &&
        routes.map((route) => {
          const isSelected = route.id === selectedId;
          const color = route.recommended ? "#2563eb" : "#6b7280";
          return (
            <Polyline
              key={`line-${route.id}`}
              positions={route.geometry.map(([lon, lat]) => [lat, lon])}
              pathOptions={{
                color,
                weight: route.recommended ? (isSelected ? 7 : 6) : isSelected ? 6 : 4,
                opacity: isSelected ? 1 : 0.55,
              }}
              eventHandlers={{ click: () => onSelect(route.id) }}
            />
          );
        })}
      {routes &&
        routes.map((route) =>
          route.checkpoints.map((cp, i) => (
            <CircleMarker
              key={`cp-${route.id}-${i}`}
              center={[cp.lat, cp.lon]}
              radius={route.id === selectedId ? 7 : 5}
              pathOptions={{
                color: "#ffffff",
                weight: 1.5,
                fillColor: RISK_COLORS[cp.risk] || "#22c55e",
                fillOpacity: 0.95,
              }}
            >
              <Popup>
                <strong>Route {route.id} checkpoint</strong>
                <br />
                {cp.miles_from_start} mi from start
                <br />
                ETA: {formatEta(cp.eta)}
                <br />
                Wind: {cp.wind_mph} mph
                <br />
                Rain: {cp.rain_in_hr} in/hr
                <br />
                Snow: {cp.snow_in_hr} in/hr
                <br />
                Risk: <strong>{cp.risk}</strong>
              </Popup>
            </CircleMarker>
          ))
        )}
      {heatPoints}
    </MapContainer>
  );
}

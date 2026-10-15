function formatDuration(minutes) {
  const total = Math.round(minutes);
  const h = Math.floor(total / 60);
  const m = total % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function formatEta(iso) {
  const d = new Date(iso);
  return d.toLocaleString([], {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function RouteCard({ route, selected, onSelect }) {
  return (
    <button
      type="button"
      className={`route-card${selected ? " selected" : ""}${route.recommended ? " recommended" : ""}`}
      onClick={() => onSelect(route.id)}
    >
      <span className="route-card-head">
        <span className="route-name">Route {route.id}</span>
        {route.recommended && <span className="badge">Recommended</span>}
      </span>
      {route.recommended && route.recommendation_reason && (
        <span className="route-reason">{route.recommendation_reason}</span>
      )}
      <span className="route-stats">
        <span>{route.distance_miles} mi</span>
        <span>{formatDuration(route.duration_minutes)}</span>
        <span>Arrives {formatEta(route.destination_eta)}</span>
      </span>
      <span className="route-risk">
        <span>
          No Travel <strong>{route.no_travel_miles} mi</strong>
        </span>
        <span>
          Severe <strong>{route.severe_miles} mi</strong>
        </span>
        <span>
          High <strong>{route.high_miles} mi</strong>
        </span>
        <span>
          Avg risk <strong>{Number(route.average_risk).toFixed(2)}</strong>
        </span>
      </span>
    </button>
  );
}

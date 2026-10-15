import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchHeatmap, fetchRoutes } from "./api";
import HeatLayer from "./components/HeatLayer.jsx";
import RouteCard from "./components/RouteCard.jsx";
import RouteMap, { RISK_COLORS } from "./components/RouteMap.jsx";

function defaultDepartureLocal() {
  const d = new Date(Date.now() + 60 * 60 * 1000);
  d.setMinutes(0, 0, 0);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function App() {
  const [origin, setOrigin] = useState("Denver, CO");
  const [destination, setDestination] = useState("Kansas City, MO");
  const [departureLocal, setDepartureLocal] = useState(defaultDepartureLocal);
  const [loadWeight, setLoadWeight] = useState(35000);
  const [interval, setIntervalMiles] = useState(25);

  const [routes, setRoutes] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [submittedDeparture, setSubmittedDeparture] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [heatmapOn, setHeatmapOn] = useState(false);
  const [hourOffset, setHourOffset] = useState(0);
  const [heatPoints, setHeatPoints] = useState([]);
  const [heatError, setHeatError] = useState("");
  const debounceRef = useRef(null);

  const selectedRoute = useMemo(
    () => (routes ? routes.find((r) => r.id === selectedId) || routes[0] : null),
    [routes, selectedId]
  );

  const loadHeatmap = useCallback(
    async (route, offset, departureIso) => {
      if (!route || !departureIso) return;
      try {
        const points = await fetchHeatmap(route.geometry, offset, departureIso);
        setHeatPoints(points);
        setHeatError("");
      } catch (err) {
        setHeatPoints([]);
        setHeatError(err.message);
      }
    },
    []
  );

  // Debounced (300 ms) heatmap refresh when the slider, the toggle or the
  // selected route changes.
  useEffect(() => {
    if (!heatmapOn || !selectedRoute || !submittedDeparture) {
      setHeatPoints([]);
      return undefined;
    }
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      loadHeatmap(selectedRoute, hourOffset, submittedDeparture);
    }, 300);
    return () => clearTimeout(debounceRef.current);
  }, [heatmapOn, selectedRoute, hourOffset, submittedDeparture, loadHeatmap]);

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    if (!origin.trim() || !destination.trim()) {
      setError("Enter both an origin and a destination.");
      return;
    }
    if (!departureLocal) {
      setError("Choose a departure date and time.");
      return;
    }
    const weight = Number(loadWeight);
    if (!weight || weight <= 0) {
      setError("Load weight must be a positive number of pounds.");
      return;
    }
    const departureIso = new Date(departureLocal).toISOString();
    setLoading(true);
    try {
      const data = await fetchRoutes({
        origin: origin.trim(),
        destination: destination.trim(),
        departure_datetime: departureIso,
        load_weight_lb: weight,
        sample_interval_miles: interval,
      });
      const list = data.routes || [];
      if (list.length === 0) {
        setRoutes(null);
        setError("No routes were returned for this trip.");
        return;
      }
      setRoutes(list);
      const recommended = list.find((r) => r.recommended) || list[0];
      setSelectedId(recommended.id);
      setSubmittedDeparture(departureIso);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>Weather-Aware Truck Routing</h1>
          <p>Live routes, ETA-matched weather risk, and the safest option first.</p>
        </div>
      </header>

      <div className="layout">
        <aside className="panel">
          <form onSubmit={handleSubmit} className="trip-form">
            <label>
              Origin
              <input
                type="text"
                value={origin}
                onChange={(e) => setOrigin(e.target.value)}
                placeholder="Denver, CO"
                required
              />
            </label>
            <label>
              Destination
              <input
                type="text"
                value={destination}
                onChange={(e) => setDestination(e.target.value)}
                placeholder="Kansas City, MO"
                required
              />
            </label>
            <label>
              Departure
              <input
                type="datetime-local"
                value={departureLocal}
                onChange={(e) => setDepartureLocal(e.target.value)}
                required
              />
            </label>
            <label>
              Load weight (lb)
              <input
                type="number"
                min="1"
                step="1"
                value={loadWeight}
                onChange={(e) => setLoadWeight(e.target.value)}
                required
              />
            </label>
            <div className="field">
              <span className="field-label">Sampling interval (miles)</span>
              <div className="segmented" role="group" aria-label="Sampling interval">
                {[10, 25, 50].map((value) => (
                  <button
                    key={value}
                    type="button"
                    className={interval === value ? "active" : ""}
                    onClick={() => setIntervalMiles(value)}
                  >
                    {value}
                  </button>
                ))}
              </div>
            </div>
            <button type="submit" className="primary" disabled={loading}>
              {loading ? "Finding safest route..." : "Find safest route"}
            </button>
          </form>

          {loading && (
            <div className="spinner-wrap" aria-live="polite">
              <div className="spinner" />
              <span>Computing routes and weather...</span>
            </div>
          )}

          {error && (
            <div className="error-banner" role="alert">
              {error}
            </div>
          )}

          {!routes && !loading && !error && (
            <div className="empty-state">
              <h2>No trip yet</h2>
              <p>
                Enter an origin and destination, then choose &ldquo;Find safest
                route&rdquo;. Up to three routes will appear here with their
                weather risk, and the safest one is recommended.
              </p>
            </div>
          )}

          {routes && (
            <section className="results">
              <h2>Route options</h2>
              <div className="cards">
                {routes.map((route) => (
                  <RouteCard
                    key={route.id}
                    route={route}
                    selected={selectedRoute && route.id === selectedRoute.id}
                    onSelect={setSelectedId}
                  />
                ))}
              </div>

              <div className="heatmap-controls">
                <div className="heatmap-head">
                  <h2>Weather heatmap</h2>
                  <label className="switch">
                    <input
                      type="checkbox"
                      checked={heatmapOn}
                      onChange={(e) => setHeatmapOn(e.target.checked)}
                    />
                    <span>{heatmapOn ? "On" : "Off"}</span>
                  </label>
                </div>
                <label className="slider-label">
                  Forecast offset <strong>+{hourOffset}h</strong>
                  <input
                    type="range"
                    min="0"
                    max="48"
                    step="1"
                    value={hourOffset}
                    disabled={!heatmapOn}
                    onChange={(e) => setHourOffset(Number(e.target.value))}
                  />
                </label>
                {heatError && (
                  <div className="error-banner" role="alert">
                    {heatError}
                  </div>
                )}
                <div className="legend">
                  {Object.entries(RISK_COLORS).map(([label, color]) => (
                    <span key={label} className="legend-item">
                      <span className="dot" style={{ background: color }} />
                      {label}
                    </span>
                  ))}
                </div>
              </div>
            </section>
          )}
        </aside>

        <main className="map-wrap">
          <RouteMap
            routes={routes}
            selectedId={selectedRoute ? selectedRoute.id : null}
            onSelect={setSelectedId}
            heatPoints={
              heatmapOn && heatPoints.length > 0 ? <HeatLayer points={heatPoints} /> : null
            }
          />
        </main>
      </div>
    </div>
  );
}

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(
  /\/$/,
  ""
);

async function parseError(response) {
  try {
    const data = await response.json();
    if (data && data.error) return data.error;
  } catch {
    // fall through to a generic message
  }
  return `Request failed with status ${response.status}`;
}

export async function fetchRoutes(payload) {
  let response;
  try {
    response = await fetch(`${API_BASE}/api/routes/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    throw new Error("Could not reach the backend. Is it running?");
  }
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

// Route geometries can contain thousands of points, which would exceed
// URL length limits on a GET request. The heatmap only samples every
// ~10 miles, so an evenly decimated polyline (at most 150 points,
// coordinates rounded to 5 decimal places) preserves the corridor shape
// while keeping the request URL short.
function decimate(geometry, maxPoints = 150) {
  const rounded = geometry.map(([lon, lat]) => [
    Math.round(lon * 1e5) / 1e5,
    Math.round(lat * 1e5) / 1e5,
  ]);
  if (rounded.length <= maxPoints) return rounded;
  const step = (rounded.length - 1) / (maxPoints - 1);
  const out = [];
  for (let i = 0; i < maxPoints; i += 1) {
    out.push(rounded[Math.round(i * step)]);
  }
  return out;
}

export async function fetchHeatmap(geometry, hourOffset, departureDatetime) {
  const params = new URLSearchParams({
    geometry: JSON.stringify({ type: "LineString", coordinates: decimate(geometry) }),
    hour_offset: String(hourOffset),
    departure_datetime: departureDatetime,
  });
  let response;
  try {
    response = await fetch(`${API_BASE}/api/heatmap/?${params.toString()}`);
  } catch {
    throw new Error("Could not reach the backend for the heatmap.");
  }
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

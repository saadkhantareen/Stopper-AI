# Weather-Aware Truck Routing

A web app that helps a truck driver choose the safest route between two
places. The driver enters an origin, a destination, a departure date/time
and a load weight. The app generates up to 3 route options, samples the
weather forecast along each route at the driver's estimated arrival time
at each checkpoint, classifies weather risk with fixed rules, recommends
the safest route, shows everything on an interactive map, and shows a
weather heatmap along the trip corridor with a 0-48 hour forecast slider.

## Tech stack

- Backend: Python + Django + Django REST Framework (no database content,
  no user accounts)
- Frontend: React (Vite) + Leaflet (react-leaflet) + leaflet.heat
- All external APIs are free: Nominatim (geocoding), OpenRouteService
  (routing, primary), OSRM public server (routing fallback), Open-Meteo
  (weather)

## How it works

1. Origin and destination are geocoded with Nominatim. If a place cannot
   be found, the error names the input that failed.
2. Routes are fetched from OpenRouteService when `ORS_API_KEY` is set
   (3 alternatives requested). If the key is not set or ORS fails, the
   app falls back to the public OSRM server. OSRM often returns only
   1-2 alternatives; the app works with however many distinct routes
   (1-3) come back.
3. Each route's polyline is walked with haversine distances. A
   checkpoint is placed every sampling interval (10, 25 or 50 miles,
   default 25), plus one at the destination. A checkpoint's ETA is
   `departure + route duration x (distance along route / total distance)`.
4. For each checkpoint, Open-Meteo hourly weather (wind mph, rain in/hr,
   snowfall in/hr) is fetched for the hour containing the ETA. Responses
   are cached in memory keyed by (rounded lat, rounded lon, hour).
5. Each checkpoint is classified with the risk table and load rules
   below, route risk is aggregated, and routes are ranked. The winner is
   marked `recommended` with a one-line reason.
6. The heatmap endpoint samples points every ~10 miles along the chosen
   route and returns the risk score at `departure + hour_offset`.

## Risk table

Lower bounds are inclusive.

| Condition    | Low    | Moderate  | High      | Severe    | No Travel |
| ------------ | ------ | --------- | --------- | --------- | --------- |
| Wind (mph)   | < 25   | 25-34     | 35-44     | 45-54     | >= 55     |
| Rain (in/hr) | < 0.10 | 0.10-0.25 | 0.25-0.50 | 0.50-1.00 | > 1.00    |
| Snow (in/hr) | < 0.5  | 0.5-1.0   | 1.0-2.0   | 2.0-3.0   | > 3.0     |

Scores: Low 0, Moderate 1, High 2, Severe 3, No Travel 4. A checkpoint's
risk is the maximum of its wind (after load rules), rain and snow bands.

## Load rules

Applied to the wind band only, before taking the maximum:

- Wind >= 55 mph -> No Travel, for any load.
- Wind 45-54 mph AND load > 30,000 lb -> No Travel.
- Wind 35-44 mph AND load > 40,000 lb -> Severe.

## Route aggregation and ranking

Each checkpoint accounts for one interval of miles; the final checkpoint
accounts for the remaining distance. Per route the app sums No Travel,
Severe and High miles, and computes `average_risk` as the mean of the
checkpoint scores.

Routes are ranked ascending by:

1. Fewest No Travel miles
2. Fewest Severe miles
3. Fewest High miles
4. Lowest average risk
5. Shortest duration

**Documented interpretation:** the original brief lists Severe first and
omits No Travel from the ranking. No Travel miles are ranked first here
because No Travel is the most severe band, so putting it first is the
safer interpretation.

## API

### POST /api/routes/

Request:

```json
{
  "origin": "Denver, CO",
  "destination": "Kansas City, MO",
  "departure_datetime": "2026-10-16T08:00:00Z",
  "load_weight_lb": 35000,
  "sample_interval_miles": 25
}
```

Response: `{ "routes": [...] }`. Each route object contains `id`,
`distance_miles`, `duration_minutes`, `destination_eta`,
`no_travel_miles`, `severe_miles`, `high_miles`, `average_risk`,
`recommended` (boolean), `recommendation_reason`, `geometry` (an array
of `[lon, lat]` pairs) and `checkpoints` (each with `lat`, `lon`,
`miles_from_start`, `eta`, `wind_mph`, `rain_in_hr`, `snow_in_hr`,
`risk`).

Errors return `{ "error": "..." }` with HTTP 400 for bad input and
HTTP 502 for upstream API failure.

### GET /api/heatmap/

Query parameters: `geometry` (URL-encoded GeoJSON LineString of the
chosen route), `hour_offset` (0-48), `departure_datetime` (ISO).

Returns a JSON array of `{ "lat": ..., "lon": ..., "intensity": 0-4 }`,
sampled every ~10 miles along the geometry, where intensity is the risk
score of that point's worst condition at `departure + hour_offset`.

## Run locally

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Optional: export ORS_API_KEY to use OpenRouteService; without it the
# OSRM fallback is used automatically.
python manage.py runserver 8000
```

The API is then at http://localhost:8000/api/routes/ and
http://localhost:8000/api/heatmap/.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The app is then at http://localhost:5173. To point it at a different
backend, set `VITE_API_BASE_URL` (see `.env.example`).

### Tests

```bash
cd backend
python manage.py test routing -v 2
```

The suite covers every boundary of the risk table (wind 24.9 / 25 /
34.9 / 35 / 44.9 / 45 / 54.9 / 55; rain 0.09 / 0.10 / 0.25 / 0.50 / 1.00 /
1.01; snow 0.4 / 0.5 / 1.0 / 2.0 / 3.0 / 3.1), the load rules at exactly
30,000 vs 30,001 lb and 40,000 vs 40,001 lb, mile aggregation, checkpoint
sampling, and the ranking order including the No Travel-first rule.

## Deployment

Configuration is via environment variables (see `.env.example`):

- Backend: serves through gunicorn (`backend/Procfile` is included for
  Render / Railway). Set `ALLOWED_HOSTS` and `CORS_ALLOWED_ORIGINS` for
  the deployed origins, plus `ORS_API_KEY` and a `DJANGO_SECRET_KEY`.
- Frontend: production build (`npm run build`) is ready for Vercel; set
  `VITE_API_BASE_URL` to the deployed backend URL.

## Assumptions

- The hourly forecast matched to a checkpoint is the entry for the hour
  containing the checkpoint's ETA.
- Snowfall is requested from Open-Meteo directly in inches
  (`snowfall_unit=inch`), as are rain (inches) and wind speed (mph), so
  no unit conversions are needed before classification.
- Open-Meteo forecasts cover 16 days; departure times beyond that
  horizon return a clear error.
- ETAs assume constant progress along the route (no rest breaks).

## API credits

- Geocoding: [Nominatim](https://nominatim.openstreetmap.org/) / OpenStreetMap
- Routing: [OpenRouteService](https://openrouteservice.org/) and the
  [OSRM](https://router.project-osrm.org/) public server
- Weather: [Open-Meteo](https://open-meteo.com/)
- Map tiles: [OpenStreetMap](https://www.openstreetmap.org/copyright)

## Project structure

```
backend/
  config/            Django project (settings read CORS / hosts from env)
  routing/
    risk_engine.py   Pure risk rules (no Django/HTTP imports)
    geo_utils.py     Haversine + checkpoint sampling (pure)
    services/        Geocoding, routing and weather clients
    views.py         POST /api/routes/ and GET /api/heatmap/
    tests/           Risk-engine unit tests
  requirements.txt
  Procfile
frontend/
  src/
    App.jsx          Trip form, summary cards, heatmap controls
    components/      RouteMap, RouteCard, HeatLayer
    api.js           Backend client (base URL from VITE_API_BASE_URL)
```

"""Routing via OpenRouteService (primary) with an OSRM fallback.

ORS is used when the ORS_API_KEY environment variable is set. If it is
not set, or the ORS request fails, the public OSRM server is used. OSRM
often returns only 1-2 alternatives; whatever distinct routes come back
(1-3) are used.
"""
import os

import requests

from .errors import UpstreamError

ORS_URL = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving/{coords}"


def _dedupe(routes):
    seen = set()
    unique = []
    for route in routes:
        key = tuple((round(lon, 5), round(lat, 5)) for lon, lat in route["geometry"])
        if key not in seen:
            seen.add(key)
            unique.append(route)
    return unique


def _fetch_ors(origin_lat, origin_lon, dest_lat, dest_lon, api_key):
    response = requests.post(
        ORS_URL,
        headers={
            "Authorization": api_key,
            "Content-Type": "application/json",
        },
        json={
            "coordinates": [[origin_lon, origin_lat], [dest_lon, dest_lat]],
            "alternative_routes": {
                "target_count": 3,
                "weight_factor": 1.4,
                "share_factor": 0.6,
            },
        },
        timeout=20,
    )
    if response.status_code != 200:
        raise UpstreamError(
            f"OpenRouteService failed with status {response.status_code}"
        )
    data = response.json()
    routes = []
    for feature in data.get("features", []):
        geometry = feature.get("geometry", {}).get("coordinates", [])
        summary = feature.get("properties", {}).get("summary", {})
        if geometry and "distance" in summary and "duration" in summary:
            routes.append(
                {
                    "geometry": [[float(lon), float(lat)] for lon, lat in geometry],
                    "distance_metres": float(summary["distance"]),
                    "duration_seconds": float(summary["duration"]),
                }
            )
    if not routes:
        raise UpstreamError("OpenRouteService returned no routes")
    return routes


def _fetch_osrm(origin_lat, origin_lon, dest_lat, dest_lon):
    coords = f"{origin_lon},{origin_lat};{dest_lon},{dest_lat}"
    response = requests.get(
        OSRM_URL.format(coords=coords),
        params={"alternatives": 3, "overview": "full", "geometries": "geojson"},
        timeout=30,
    )
    if response.status_code != 200:
        raise UpstreamError(f"OSRM failed with status {response.status_code}")
    data = response.json()
    if data.get("code") != "Ok":
        raise UpstreamError("OSRM could not find a route between these locations")
    routes = []
    for route in data.get("routes", []):
        geometry = route.get("geometry", {}).get("coordinates", [])
        if geometry:
            routes.append(
                {
                    "geometry": [[float(lon), float(lat)] for lon, lat in geometry],
                    "distance_metres": float(route["distance"]),
                    "duration_seconds": float(route["duration"]),
                }
            )
    if not routes:
        raise UpstreamError("OSRM returned no routes")
    return routes


def fetch_routes(origin_lat, origin_lon, dest_lat, dest_lon):
    """Return 1-3 distinct routes as dicts with geometry (a list of
    [lon, lat] pairs), distance_metres and duration_seconds."""
    api_key = os.environ.get("ORS_API_KEY", "").strip()
    ors_error = None
    if api_key:
        try:
            return _dedupe(_fetch_ors(origin_lat, origin_lon, dest_lat, dest_lon, api_key))
        except Exception as exc:  # fall through to OSRM on any ORS failure
            ors_error = exc
    try:
        return _dedupe(_fetch_osrm(origin_lat, origin_lon, dest_lat, dest_lon))
    except Exception as exc:
        if ors_error is not None:
            raise UpstreamError(
                f"Routing failed: OpenRouteService error ({ors_error}); "
                f"OSRM error ({exc})"
            ) from exc
        raise UpstreamError(f"Routing failed: {exc}") from exc

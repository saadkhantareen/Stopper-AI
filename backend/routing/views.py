"""API views: POST /api/routes/ and GET /api/heatmap/."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from rest_framework.decorators import api_view
from rest_framework.response import Response

from .geo_utils import METRES_PER_MILE, sample_points
from .risk_engine import (
    aggregate_checkpoints,
    checkpoint_risk,
    rank_routes,
    recommendation_reason,
    risk_label,
)
from .services.errors import BadInputError, UpstreamError
from .services.geocoding import geocode
from .services.routing_service import fetch_routes
from .services.weather import get_weather

VALID_INTERVALS = (10, 25, 50)


def _parse_datetime(value):
    if not value or not isinstance(value, str):
        raise BadInputError("departure_datetime is required and must be an ISO datetime string")
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BadInputError(f"departure_datetime is not a valid ISO datetime: '{value}'") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _error_response(exc):
    if isinstance(exc, BadInputError):
        return Response({"error": str(exc)}, status=400)
    return Response({"error": str(exc)}, status=502)


def _checkpoint_weather(point, eta, load_weight_lb):
    wind, rain, snow = get_weather(point["lat"], point["lon"], eta)
    risk = checkpoint_risk(wind, rain, snow, load_weight_lb)
    return {
        "lat": round(point["lat"], 6),
        "lon": round(point["lon"], 6),
        "miles_from_start": point["miles_from_start"],
        "segment_miles": point["segment_miles"],
        "eta": _iso(eta),
        "wind_mph": round(wind, 2),
        "rain_in_hr": round(rain, 3),
        "snow_in_hr": round(snow, 3),
        "risk": risk_label(risk),
        "_risk_score": int(risk),
    }


@api_view(["POST"])
def routes_view(request):
    try:
        data = request.data if isinstance(request.data, dict) else {}
        origin = str(data.get("origin") or "").strip()
        destination = str(data.get("destination") or "").strip()
        if not origin:
            raise BadInputError("origin is required")
        if not destination:
            raise BadInputError("destination is required")
        departure = _parse_datetime(data.get("departure_datetime"))

        try:
            load_weight_lb = float(data.get("load_weight_lb"))
        except (TypeError, ValueError) as exc:
            raise BadInputError("load_weight_lb is required and must be a number") from exc
        if load_weight_lb <= 0:
            raise BadInputError("load_weight_lb must be a positive number")

        interval = data.get("sample_interval_miles", 25)
        try:
            interval = int(interval)
        except (TypeError, ValueError) as exc:
            raise BadInputError("sample_interval_miles must be one of 10, 25, 50") from exc
        if interval not in VALID_INTERVALS:
            raise BadInputError("sample_interval_miles must be one of 10, 25, 50")

        origin_lat, origin_lon = geocode(origin, "origin")
        dest_lat, dest_lon = geocode(destination, "destination")

        raw_routes = fetch_routes(origin_lat, origin_lon, dest_lat, dest_lon)
        if not raw_routes:
            raise UpstreamError("No route found between origin and destination")

        built = []
        for index, raw in enumerate(raw_routes):
            distance_miles = raw["distance_metres"] / METRES_PER_MILE
            duration_seconds = raw["duration_seconds"]
            points, polyline_total = sample_points(raw["geometry"], float(interval))
            if not points:
                raise UpstreamError("A returned route had no usable geometry")

            def build(point):
                # Fraction of the route covered, measured along the same
                # polyline the checkpoints were sampled from, so the final
                # checkpoint's ETA equals the destination ETA exactly.
                fraction = (
                    point["miles_from_start"] / polyline_total if polyline_total else 0.0
                )
                eta = departure + timedelta(seconds=duration_seconds * fraction)
                return _checkpoint_weather(point, eta, load_weight_lb)

            with ThreadPoolExecutor(max_workers=4) as pool:
                checkpoints = list(pool.map(build, points))

            aggregates = aggregate_checkpoints(
                [
                    {"risk": cp["_risk_score"], "segment_miles": cp["segment_miles"]}
                    for cp in checkpoints
                ]
            )
            for cp in checkpoints:
                del cp["_risk_score"]
                del cp["segment_miles"]

            destination_eta = departure + timedelta(seconds=duration_seconds)
            built.append(
                {
                    "id": index + 1,
                    "distance_miles": round(distance_miles, 2),
                    "duration_minutes": round(duration_seconds / 60, 1),
                    "destination_eta": _iso(destination_eta),
                    "no_travel_miles": aggregates["no_travel_miles"],
                    "severe_miles": aggregates["severe_miles"],
                    "high_miles": aggregates["high_miles"],
                    "average_risk": aggregates["average_risk"],
                    "recommended": False,
                    "recommendation_reason": "",
                    "geometry": raw["geometry"],
                    "checkpoints": checkpoints,
                }
            )

        ranked = rank_routes(built)
        winner = ranked[0]
        winner["recommended"] = True
        winner["recommendation_reason"] = recommendation_reason(winner)

        return Response({"routes": built})
    except (BadInputError, UpstreamError) as exc:
        return _error_response(exc)
    except Exception as exc:  # never return a blank/HTML error to the client
        return Response({"error": f"Unexpected server error: {exc}"}, status=502)


@api_view(["GET"])
def heatmap_view(request):
    try:
        geometry_raw = request.query_params.get("geometry")
        if not geometry_raw:
            raise BadInputError("geometry query parameter is required")
        try:
            geometry_obj = json.loads(geometry_raw)
        except ValueError as exc:
            raise BadInputError("geometry must be a GeoJSON LineString") from exc
        if (
            not isinstance(geometry_obj, dict)
            or geometry_obj.get("type") != "LineString"
            or not isinstance(geometry_obj.get("coordinates"), list)
            or len(geometry_obj["coordinates"]) < 2
        ):
            raise BadInputError("geometry must be a GeoJSON LineString with at least 2 points")
        coordinates = geometry_obj["coordinates"]

        try:
            hour_offset = int(request.query_params.get("hour_offset", 0))
        except (TypeError, ValueError) as exc:
            raise BadInputError("hour_offset must be an integer between 0 and 48") from exc
        if hour_offset < 0 or hour_offset > 48:
            raise BadInputError("hour_offset must be between 0 and 48")

        departure = _parse_datetime(request.query_params.get("departure_datetime"))
        target_time = departure + timedelta(hours=hour_offset)

        points, _total = sample_points(coordinates, 10.0)
        if not points:
            raise BadInputError("geometry has no usable length")

        def intensity_for(point):
            wind, rain, snow = get_weather(point["lat"], point["lon"], target_time)
            # No load is supplied for the heatmap, so no load escalation
            # applies beyond the wind band itself (>= 55 mph is No Travel).
            risk = checkpoint_risk(wind, rain, snow, 0)
            return {
                "lat": round(point["lat"], 6),
                "lon": round(point["lon"], 6),
                "intensity": int(risk),
            }

        with ThreadPoolExecutor(max_workers=4) as pool:
            result = list(pool.map(intensity_for, points))
        return Response(result)
    except (BadInputError, UpstreamError) as exc:
        return _error_response(exc)
    except Exception as exc:
        return Response({"error": f"Unexpected server error: {exc}"}, status=502)


def health_view(request):
    """Lightweight health check used by uptime pingers to keep the
    free-tier host awake; performs no upstream calls."""
    from django.http import JsonResponse

    return JsonResponse({"status": "ok"})

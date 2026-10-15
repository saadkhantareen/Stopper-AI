"""Weather via Open-Meteo. No API key required.

Hourly wind speed (mph), rain (in/hr) and snowfall (in/hr) are requested
directly in imperial units. Responses are cached in memory keyed by
(round(lat, 2), round(lon, 2), hour) for resolved values, and the raw
hourly payload is cached per rounded coordinate, so repeated calls for
the same place and hour never refetch.
"""
import threading
from datetime import timezone

import requests

from .errors import UpstreamError

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

_lock = threading.Lock()
_hourly_cache = {}  # (round(lat,2), round(lon,2)) -> {hour_key: (wind, rain, snow)}
_value_cache = {}  # (round(lat,2), round(lon,2), hour_key) -> (wind, rain, snow)


def _hour_key(when):
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    when = when.astimezone(timezone.utc)
    return when.strftime("%Y-%m-%dT%H:00")


def _fetch_hourly(lat, lon):
    key = (round(lat, 2), round(lon, 2))
    with _lock:
        if key in _hourly_cache:
            return _hourly_cache[key]
    try:
        response = requests.get(
            OPEN_METEO_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "wind_speed_10m,rain,snowfall",
                "wind_speed_unit": "mph",
                "precipitation_unit": "inch",
                "snowfall_unit": "inch",
                "forecast_days": 16,
                "timezone": "UTC",
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        raise UpstreamError(f"Weather service is unavailable: {exc}") from exc
    if response.status_code != 200:
        raise UpstreamError(
            f"Weather service failed with status {response.status_code}"
        )
    try:
        hourly = response.json()["hourly"]
        times = hourly["time"]
        winds = hourly["wind_speed_10m"]
        rains = hourly["rain"]
        snows = hourly["snowfall"]
    except (ValueError, KeyError, TypeError) as exc:
        raise UpstreamError("Weather service returned an unreadable response") from exc
    by_hour = {}
    for i, time_str in enumerate(times):
        by_hour[time_str[:13] + ":00"] = (
            float(winds[i] or 0.0),
            float(rains[i] or 0.0),
            float(snows[i] or 0.0),
        )
    with _lock:
        _hourly_cache[key] = by_hour
    return by_hour


def get_weather(lat, lon, when):
    """Return (wind_mph, rain_in_hr, snow_in_hr) for the hour containing
    ``when`` (a datetime). Raises UpstreamError if that hour is outside
    the available forecast or the service fails."""
    hour = _hour_key(when)
    cache_key = (round(lat, 2), round(lon, 2), hour)
    with _lock:
        if cache_key in _value_cache:
            return _value_cache[cache_key]
    by_hour = _fetch_hourly(lat, lon)
    if hour not in by_hour:
        raise UpstreamError(
            f"No weather forecast is available for {hour} UTC at "
            f"({lat:.2f}, {lon:.2f}); the forecast horizon is 16 days"
        )
    value = by_hour[hour]
    with _lock:
        _value_cache[cache_key] = value
    return value

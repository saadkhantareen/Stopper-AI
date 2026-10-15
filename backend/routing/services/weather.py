"""Weather via Open-Meteo. No API key required.

Hourly wind speed (mph), rain (in/hr) and snowfall (in/hr) are requested
directly in imperial units. Responses are cached in memory keyed by
(round(lat, 2), round(lon, 2), hour) for resolved values, and the raw
hourly payload is cached per rounded coordinate, so repeated calls for
the same place and hour never refetch.

Open-Meteo rate-limits bursts (HTTP 429). To stay within the limit,
at most 3 weather requests run concurrently, and a 429 (or a transient
5xx) is retried with backoff, honouring the Retry-After header, instead
of failing the whole trip calculation on the first limited response.
"""
import threading
from datetime import timezone
from time import sleep

import requests

from .errors import UpstreamError

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

_MAX_ATTEMPTS = 4
_request_slots = threading.Semaphore(3)

_lock = threading.Lock()
_hourly_cache = {}  # (round(lat,2), round(lon,2)) -> {hour_key: (wind, rain, snow)}
_value_cache = {}  # (round(lat,2), round(lon,2), hour_key) -> (wind, rain, snow)


def _hour_key(when):
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    when = when.astimezone(timezone.utc)
    return when.strftime("%Y-%m-%dT%H:00")


def _retry_delay(response, attempt):
    """Seconds to wait before the next attempt: the Retry-After header
    when the service sends one (capped), otherwise exponential backoff."""
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), 10.0)
            except ValueError:
                pass
    return min(1.0 * (2**attempt), 8.0)


def _get_forecast(params):
    """GET the forecast, retrying rate-limit / transient failures."""
    last_status = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            with _request_slots:
                response = requests.get(OPEN_METEO_URL, params=params, timeout=20)
        except requests.RequestException as exc:
            if attempt == _MAX_ATTEMPTS - 1:
                raise UpstreamError(f"Weather service is unavailable: {exc}") from exc
            sleep(_retry_delay(None, attempt))
            continue
        if response.status_code == 200:
            return response
        last_status = response.status_code
        retryable = response.status_code == 429 or response.status_code >= 500
        if not retryable or attempt == _MAX_ATTEMPTS - 1:
            break
        sleep(_retry_delay(response, attempt))
    if last_status == 429:
        raise UpstreamError(
            "Weather service rate limit reached (429) after retries; "
            "please wait a minute and try again"
        )
    raise UpstreamError(f"Weather service failed with status {last_status}")


def _fetch_hourly(lat, lon):
    key = (round(lat, 2), round(lon, 2))
    with _lock:
        if key in _hourly_cache:
            return _hourly_cache[key]
    response = _get_forecast(
        {
            "latitude": lat,
            "longitude": lon,
            "hourly": "wind_speed_10m,rain,snowfall",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "snowfall_unit": "inch",
            "forecast_days": 16,
            "timezone": "UTC",
        }
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

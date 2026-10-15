"""Geocoding via Nominatim (OpenStreetMap). No API key required."""
import requests

from .errors import BadInputError, UpstreamError

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "WeatherAwareTruckRouting/1.0 (truck routing assessment app)"


def geocode(place: str, field_name: str):
    """Return (lat, lon) for ``place``.

    Raises BadInputError naming the input when Nominatim finds nothing,
    and UpstreamError when the service itself fails.
    """
    try:
        response = requests.get(
            NOMINATIM_URL,
            params={"format": "json", "limit": 1, "q": place},
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise UpstreamError(f"Geocoding service is unavailable: {exc}") from exc
    if response.status_code != 200:
        raise UpstreamError(
            f"Geocoding service failed with status {response.status_code}"
        )
    try:
        results = response.json()
    except ValueError as exc:
        raise UpstreamError("Geocoding service returned an unreadable response") from exc
    if not results:
        raise BadInputError(f"Could not find {field_name}: '{place}'")
    try:
        return float(results[0]["lat"]), float(results[0]["lon"])
    except (KeyError, TypeError, ValueError) as exc:
        raise UpstreamError("Geocoding service returned an incomplete response") from exc

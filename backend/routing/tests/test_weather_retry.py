"""Tests for the weather client's rate-limit handling.

A 429 from Open-Meteo must be retried with backoff (the free tier limits
bursts when many checkpoint forecasts are fetched for one trip), and a
persistent 429 must surface as a clear UpstreamError, not a crash.
"""
from datetime import datetime, timezone
from unittest import mock

from django.test import SimpleTestCase

from routing.services import weather
from routing.services.errors import UpstreamError

PAYLOAD = {
    "hourly": {
        "time": ["2026-10-17T08:00"],
        "wind_speed_10m": [12.0],
        "rain": [0.05],
        "snowfall": [0.0],
    }
}
WHEN = datetime(2026, 10, 17, 8, 37, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload


class WeatherRetryTests(SimpleTestCase):
    def setUp(self):
        weather._hourly_cache.clear()
        weather._value_cache.clear()

    def test_429_is_retried_and_then_succeeds(self):
        responses = [
            FakeResponse(429, headers={"Retry-After": "0"}),
            FakeResponse(200, PAYLOAD),
        ]
        with mock.patch.object(
            weather.requests, "get", side_effect=responses
        ) as get, mock.patch.object(weather, "sleep"):
            result = weather.get_weather(39.74, -104.99, WHEN)
        self.assertEqual(result, (12.0, 0.05, 0.0))
        self.assertEqual(get.call_count, 2)

    def test_persistent_429_raises_clear_error(self):
        with mock.patch.object(
            weather.requests, "get", return_value=FakeResponse(429)
        ) as get, mock.patch.object(weather, "sleep"):
            with self.assertRaises(UpstreamError) as ctx:
                weather.get_weather(40.01, -105.27, WHEN)
        self.assertIn("rate limit", str(ctx.exception).lower())
        self.assertEqual(get.call_count, weather._MAX_ATTEMPTS)

    def test_other_errors_are_not_retried(self):
        with mock.patch.object(
            weather.requests, "get", return_value=FakeResponse(400)
        ) as get, mock.patch.object(weather, "sleep"):
            with self.assertRaises(UpstreamError):
                weather.get_weather(41.25, -95.93, WHEN)
        self.assertEqual(get.call_count, 1)

"""Unit tests for the pure risk engine.

Covers EVERY boundary in the fixed risk table, both load rules at their
exact load thresholds, mile aggregation, checkpoint sampling (the final
checkpoint accounts for the remaining distance) and the ranking order,
including the documented No Travel-first rule.

Run from backend/:  python manage.py test routing -v 2
"""
from django.test import SimpleTestCase

from routing.geo_utils import sample_points
from routing.risk_engine import (
    Risk,
    aggregate_checkpoints,
    checkpoint_risk,
    rain_risk,
    rank_routes,
    recommendation_reason,
    snow_risk,
    wind_risk,
    wind_risk_with_load,
)


class WindBoundaryTests(SimpleTestCase):
    def test_all_wind_boundaries(self):
        cases = [
            (24.9, Risk.LOW),
            (25, Risk.MODERATE),
            (34.9, Risk.MODERATE),
            (35, Risk.HIGH),
            (44.9, Risk.HIGH),
            (45, Risk.SEVERE),
            (54.9, Risk.SEVERE),
            (55, Risk.NO_TRAVEL),
        ]
        for value, expected in cases:
            with self.subTest(wind=value):
                self.assertEqual(wind_risk(value), expected)


class RainBoundaryTests(SimpleTestCase):
    def test_all_rain_boundaries(self):
        cases = [
            (0.09, Risk.LOW),
            (0.10, Risk.MODERATE),
            (0.25, Risk.HIGH),
            (0.50, Risk.SEVERE),
            (1.00, Risk.SEVERE),  # No Travel is strictly > 1.00
            (1.01, Risk.NO_TRAVEL),
        ]
        for value, expected in cases:
            with self.subTest(rain=value):
                self.assertEqual(rain_risk(value), expected)


class SnowBoundaryTests(SimpleTestCase):
    def test_all_snow_boundaries(self):
        cases = [
            (0.4, Risk.LOW),
            (0.5, Risk.MODERATE),
            (1.0, Risk.HIGH),
            (2.0, Risk.SEVERE),
            (3.0, Risk.SEVERE),  # No Travel is strictly > 3.0
            (3.1, Risk.NO_TRAVEL),
        ]
        for value, expected in cases:
            with self.subTest(snow=value):
                self.assertEqual(snow_risk(value), expected)


class LoadRuleTests(SimpleTestCase):
    def test_wind_55_is_no_travel_for_any_load(self):
        self.assertEqual(wind_risk_with_load(55, 1), Risk.NO_TRAVEL)
        self.assertEqual(wind_risk_with_load(60, 100_000), Risk.NO_TRAVEL)

    def test_45_to_54_band_at_exactly_30000_vs_30001(self):
        # Rule applies only when load is strictly greater than 30,000 lb.
        self.assertEqual(wind_risk_with_load(50, 30_000), Risk.SEVERE)
        self.assertEqual(wind_risk_with_load(50, 30_001), Risk.NO_TRAVEL)
        self.assertEqual(wind_risk_with_load(45, 30_001), Risk.NO_TRAVEL)
        self.assertEqual(wind_risk_with_load(54.9, 30_000), Risk.SEVERE)

    def test_35_to_44_band_at_exactly_40000_vs_40001(self):
        # Rule applies only when load is strictly greater than 40,000 lb.
        self.assertEqual(wind_risk_with_load(40, 40_000), Risk.HIGH)
        self.assertEqual(wind_risk_with_load(40, 40_001), Risk.SEVERE)
        self.assertEqual(wind_risk_with_load(35, 40_001), Risk.SEVERE)
        self.assertEqual(wind_risk_with_load(44.9, 40_000), Risk.HIGH)

    def test_load_rules_do_not_escalate_other_bands(self):
        self.assertEqual(wind_risk_with_load(30, 100_000), Risk.MODERATE)
        self.assertEqual(wind_risk_with_load(24.9, 100_000), Risk.LOW)
        self.assertEqual(wind_risk_with_load(50, 10_000), Risk.SEVERE)

    def test_checkpoint_risk_is_max_of_all_conditions(self):
        self.assertEqual(checkpoint_risk(10, 0.6, 0, 10_000), Risk.SEVERE)
        self.assertEqual(checkpoint_risk(10, 0, 0.6, 10_000), Risk.MODERATE)
        # Load-escalated wind beats calm rain/snow.
        self.assertEqual(checkpoint_risk(50, 0, 0, 30_001), Risk.NO_TRAVEL)
        # Rain No Travel beats a merely Severe wind.
        self.assertEqual(checkpoint_risk(50, 1.01, 0, 10_000), Risk.NO_TRAVEL)


def _cp(risk, segment):
    return {"risk": risk, "segment_miles": segment}


class AggregationTests(SimpleTestCase):
    def test_mile_aggregation_and_average(self):
        result = aggregate_checkpoints(
            [
                _cp(Risk.NO_TRAVEL, 25),
                _cp(Risk.SEVERE, 25),
                _cp(Risk.HIGH, 25),
                _cp(Risk.LOW, 10),  # final checkpoint: remaining distance
            ]
        )
        self.assertEqual(result["no_travel_miles"], 25)
        self.assertEqual(result["severe_miles"], 25)
        self.assertEqual(result["high_miles"], 25)
        # Mean of checkpoint scores (4 + 3 + 2 + 0) / 4, not mile-weighted.
        self.assertAlmostEqual(result["average_risk"], 2.25)

    def test_moderate_and_low_miles_are_not_counted_as_high(self):
        result = aggregate_checkpoints([_cp(Risk.MODERATE, 25), _cp(Risk.LOW, 25)])
        self.assertEqual(result["no_travel_miles"], 0)
        self.assertEqual(result["severe_miles"], 0)
        self.assertEqual(result["high_miles"], 0)
        self.assertAlmostEqual(result["average_risk"], 0.5)

    def test_empty_aggregation(self):
        result = aggregate_checkpoints([])
        self.assertEqual(result["average_risk"], 0.0)


def _route(name, no_travel=0, severe=0, high=0, average=0.0, minutes=600):
    return {
        "id": name,
        "no_travel_miles": no_travel,
        "severe_miles": severe,
        "high_miles": high,
        "average_risk": average,
        "duration_minutes": minutes,
    }


class RankingTests(SimpleTestCase):
    def test_no_travel_miles_rank_first(self):
        # A route with No Travel miles must lose even to a route with
        # more Severe miles, more High miles, worse average risk and a
        # longer duration. This is the documented No Travel-first rule.
        with_no_travel = _route("a", no_travel=25, severe=0, high=0, average=0.5, minutes=100)
        without = _route("b", no_travel=0, severe=50, high=50, average=2.0, minutes=900)
        ranked = rank_routes([with_no_travel, without])
        self.assertEqual(ranked[0]["id"], "b")

    def test_severe_then_high_then_average_then_duration(self):
        base = _route("base", severe=25, high=25, average=1.0, minutes=500)
        fewer_severe = _route("fewer-severe", severe=0, high=99, average=3.0, minutes=999)
        self.assertEqual(rank_routes([base, fewer_severe])[0]["id"], "fewer-severe")

        fewer_high = _route("fewer-high", severe=25, high=0, average=3.0, minutes=999)
        self.assertEqual(rank_routes([base, fewer_high])[0]["id"], "fewer-high")

        lower_average = _route("lower-average", severe=25, high=25, average=0.5, minutes=999)
        self.assertEqual(rank_routes([base, lower_average])[0]["id"], "lower-average")

        shorter = _route("shorter", severe=25, high=25, average=1.0, minutes=400)
        self.assertEqual(rank_routes([base, shorter])[0]["id"], "shorter")

    def test_recommendation_reason_mentions_clean_route(self):
        reason = recommendation_reason(_route("w", no_travel=0, severe=0, high=0, average=0.2))
        self.assertIn("No No Travel, Severe or High miles", reason)
        reason = recommendation_reason(_route("w", no_travel=0, severe=0, high=25, average=0.2))
        self.assertIn("No No Travel or Severe miles", reason)


class SamplingTests(SimpleTestCase):
    # A straight line east: [lon, lat] pairs roughly 69.09 miles apart
    # per degree of longitude at the equator.
    GEOMETRY = [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]]

    def test_checkpoints_sum_to_total_and_final_takes_remainder(self):
        points, total = sample_points(self.GEOMETRY, 25.0)
        self.assertAlmostEqual(sum(p["segment_miles"] for p in points), total, places=3)
        self.assertEqual(points[-1]["miles_from_start"], round(total, 4))
        for point in points[:-1]:
            self.assertEqual(point["segment_miles"], 25.0)
        self.assertLess(points[-1]["segment_miles"], 25.0)
        self.assertGreater(points[-1]["segment_miles"], 0.0)

    def test_exact_multiple_has_no_duplicate_destination(self):
        points, total = sample_points(self.GEOMETRY, total / 2 if (total := sample_points(self.GEOMETRY, 10.0)[1]) else 10.0)
        self.assertEqual(len(points), 2)

    def test_short_route_has_single_destination_checkpoint(self):
        points, total = sample_points([[0.0, 0.0], [0.1, 0.0]], 25.0)
        self.assertEqual(len(points), 1)
        self.assertAlmostEqual(points[0]["segment_miles"], total, places=3)

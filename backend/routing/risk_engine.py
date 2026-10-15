"""Pure weather-risk engine.

This module implements the fixed risk rules of the assessment exactly.
It has no Django, HTTP or I/O dependencies, so it can be unit-tested in
isolation and reused from any caller.

Risk bands (lower bounds inclusive):

    Condition     Low      Moderate    High        Severe      No Travel
    Wind (mph)    < 25     25-34       35-44       45-54       >= 55
    Rain (in/hr)  < 0.10   0.10-0.25   0.25-0.50   0.50-1.00   > 1.00
    Snow (in/hr)  < 0.5    0.5-1.0     1.0-2.0     2.0-3.0     > 3.0

Note the upper bounds for rain and snow: exactly 1.00 in/hr of rain and
exactly 3.0 in/hr of snow are Severe, because No Travel is defined as
strictly greater than those values.

Load rules (applied to the wind band only, before taking the maximum):
    * Wind >= 55 mph                       -> No Travel, for any load.
    * Wind 45-54 mph AND load > 30,000 lb  -> No Travel.
    * Wind 35-44 mph AND load > 40,000 lb  -> Severe.

Checkpoint risk = max(wind band after load rules, rain band, snow band).
Scores: Low 0, Moderate 1, High 2, Severe 3, No Travel 4.

Route ranking (ascending; first differing criterion decides):
    1. fewest No Travel miles
    2. fewest Severe miles
    3. fewest High miles
    4. lowest average risk (mean of checkpoint scores)
    5. shortest duration
Criterion 1 is a deliberate safety interpretation: the original brief
lists Severe first and omits No Travel; putting No Travel first is
safer because it is the most severe band.
"""
from __future__ import annotations

from enum import IntEnum


class Risk(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def label(self) -> str:
        return _LABELS[self]


_LABELS = {
    Risk.LOW: "Low",
    Risk.MODERATE: "Moderate",
    Risk.HIGH: "High",
    Risk.SEVERE: "Severe",
    Risk.NO_TRAVEL: "No Travel",
}


def risk_label(risk) -> str:
    """Human-readable label for a Risk (or its integer score)."""
    return Risk(int(risk)).label


def wind_risk(wind_mph: float) -> Risk:
    if wind_mph >= 55:
        return Risk.NO_TRAVEL
    if wind_mph >= 45:
        return Risk.SEVERE
    if wind_mph >= 35:
        return Risk.HIGH
    if wind_mph >= 25:
        return Risk.MODERATE
    return Risk.LOW


def rain_risk(rain_in_hr: float) -> Risk:
    if rain_in_hr > 1.00:
        return Risk.NO_TRAVEL
    if rain_in_hr >= 0.50:
        return Risk.SEVERE
    if rain_in_hr >= 0.25:
        return Risk.HIGH
    if rain_in_hr >= 0.10:
        return Risk.MODERATE
    return Risk.LOW


def snow_risk(snow_in_hr: float) -> Risk:
    if snow_in_hr > 3.0:
        return Risk.NO_TRAVEL
    if snow_in_hr >= 2.0:
        return Risk.SEVERE
    if snow_in_hr >= 1.0:
        return Risk.HIGH
    if snow_in_hr >= 0.5:
        return Risk.MODERATE
    return Risk.LOW


def wind_risk_with_load(wind_mph: float, load_weight_lb: float) -> Risk:
    """Wind band after applying the load rules."""
    band = wind_risk(wind_mph)
    if wind_mph >= 55:
        return Risk.NO_TRAVEL
    if 45 <= wind_mph < 55 and load_weight_lb > 30_000:
        return Risk.NO_TRAVEL
    if 35 <= wind_mph < 45 and load_weight_lb > 40_000:
        return max(band, Risk.SEVERE)
    return band


def checkpoint_risk(
    wind_mph: float, rain_in_hr: float, snow_in_hr: float, load_weight_lb: float
) -> Risk:
    """Final risk for one checkpoint: the worst of its three conditions."""
    return max(
        wind_risk_with_load(wind_mph, load_weight_lb),
        rain_risk(rain_in_hr),
        snow_risk(snow_in_hr),
    )


def aggregate_checkpoints(checkpoints) -> dict:
    """Aggregate per-route risk figures.

    Each checkpoint is a mapping with at least ``risk`` (a Risk or score)
    and ``segment_miles`` (the miles that checkpoint accounts for: one
    sampling interval, or the remaining distance for the final one).

    Returns a dict with ``no_travel_miles``, ``severe_miles``,
    ``high_miles`` and ``average_risk`` (the plain mean of checkpoint
    scores).
    """
    no_travel = severe = high = 0.0
    scores = []
    for cp in checkpoints:
        risk = Risk(int(cp["risk"]))
        segment = float(cp["segment_miles"])
        scores.append(int(risk))
        if risk == Risk.NO_TRAVEL:
            no_travel += segment
        elif risk == Risk.SEVERE:
            severe += segment
        elif risk == Risk.HIGH:
            high += segment
    average = sum(scores) / len(scores) if scores else 0.0
    return {
        "no_travel_miles": round(no_travel, 2),
        "severe_miles": round(severe, 2),
        "high_miles": round(high, 2),
        "average_risk": round(average, 4),
    }


def route_rank_key(summary) -> tuple:
    """Sort key implementing the ranking order (ascending = best first)."""
    return (
        float(summary["no_travel_miles"]),
        float(summary["severe_miles"]),
        float(summary["high_miles"]),
        float(summary["average_risk"]),
        float(summary["duration_minutes"]),
    )


def rank_routes(summaries) -> list:
    """Return route summaries sorted best-first. Input is not mutated
    in order; a new sorted list is returned."""
    return sorted(summaries, key=route_rank_key)


def recommendation_reason(summary) -> str:
    """One-line human reason for why the winning route is recommended."""
    no_travel = float(summary["no_travel_miles"])
    severe = float(summary["severe_miles"])
    high = float(summary["high_miles"])
    average = float(summary["average_risk"])
    if no_travel == 0 and severe == 0 and high == 0:
        return "No No Travel, Severe or High miles; safest route overall"
    if no_travel == 0 and severe == 0:
        return "No No Travel or Severe miles; lowest average risk"
    if no_travel == 0:
        return f"Fewest Severe miles ({severe:g}) and no No Travel miles"
    return (
        f"Fewest No Travel miles ({no_travel:g}); "
        f"average risk {average:.2f}"
    )

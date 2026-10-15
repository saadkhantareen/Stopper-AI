"""Pure geometry helpers: haversine distances and checkpoint sampling.

No Django or HTTP dependencies.
"""
from __future__ import annotations

import math

EARTH_RADIUS_MILES = 3958.7613
METRES_PER_MILE = 1609.344


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(a)))


def _interpolate(lon1, lat1, lon2, lat2, fraction):
    return [lon1 + (lon2 - lon1) * fraction, lat1 + (lat2 - lat1) * fraction]


def sample_points(geometry, interval_miles: float):
    """Walk a [lon, lat] polyline and place points every ``interval_miles``.

    A point is placed at each whole multiple of the interval and one final
    point at the destination. Returns ``(points, total_miles)`` where each
    point is a dict with ``lat``, ``lon``, ``miles_from_start`` and
    ``segment_miles`` (the miles that point accounts for: the interval,
    or the remaining distance for the final point).
    """
    if not geometry or len(geometry) < 2:
        return [], 0.0
    if interval_miles <= 0:
        raise ValueError("interval_miles must be positive")

    # Cumulative distance at each vertex.
    cumulative = [0.0]
    for i in range(1, len(geometry)):
        lon1, lat1 = geometry[i - 1]
        lon2, lat2 = geometry[i]
        cumulative.append(cumulative[-1] + haversine_miles(lat1, lon1, lat2, lon2))
    total = cumulative[-1]
    if total == 0:
        return [], 0.0

    targets = []
    t = float(interval_miles)
    while t < total - 1e-9:
        targets.append(t)
        t += interval_miles
    targets.append(total)

    points = []
    seg_idx = 0
    previous = 0.0
    for target in targets:
        while seg_idx < len(geometry) - 2 and cumulative[seg_idx + 1] < target:
            seg_idx += 1
        seg_start = cumulative[seg_idx]
        seg_end = cumulative[seg_idx + 1]
        seg_len = seg_end - seg_start
        fraction = 0.0 if seg_len == 0 else (target - seg_start) / seg_len
        fraction = min(1.0, max(0.0, fraction))
        lon1, lat1 = geometry[seg_idx]
        lon2, lat2 = geometry[seg_idx + 1]
        if target == total:
            lon, lat = geometry[-1]
        else:
            lon, lat = _interpolate(lon1, lat1, lon2, lat2, fraction)
        points.append(
            {
                "lat": lat,
                "lon": lon,
                "miles_from_start": round(target, 4),
                "segment_miles": round(target - previous, 4),
            }
        )
        previous = target
    return points, total

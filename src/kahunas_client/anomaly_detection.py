"""Analytics and anomaly detection for Kahunas check-in timeseries.

Detects significant changes in client health metrics by comparing
consecutive check-in data points. Supports both percentage-based
thresholds (for body measurements) and absolute-change thresholds
(for lifestyle ratings on a 1-10 scale).

Thresholds are fully configurable via KahunasConfig environment
variables (KAHUNAS_ANOMALY_*).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Category definitions for threshold types
BODY_METRICS = frozenset({"weight", "waist", "hips", "biceps", "thighs"})
LIFESTYLE_METRICS = frozenset(
    {
        "sleep_quality",
        "nutrition_adherence",
        "workout_rating",
        "stress_level",
        "energy_level",
        "mood_wellbeing",
    }
)
MINIMUM_CHECK_METRICS = frozenset({"sleep_quality", "energy_level"})

# Default thresholds per metric category
DEFAULT_THRESHOLDS: dict[str, dict[str, Any]] = {
    # Body metrics — percentage change thresholds
    "weight": {"type": "pct", "threshold": 20.0, "label": "Weight"},
    "waist": {"type": "pct", "threshold": 15.0, "label": "Waist"},
    "hips": {"type": "pct", "threshold": 15.0, "label": "Hips"},
    "biceps": {"type": "pct", "threshold": 15.0, "label": "Biceps"},
    "thighs": {"type": "pct", "threshold": 15.0, "label": "Thighs"},
    # Lifestyle metrics — absolute change thresholds (1-10 scale)
    "sleep_quality": {"type": "abs", "threshold": 3.0, "label": "Sleep Quality"},
    "nutrition_adherence": {"type": "abs", "threshold": 3.0, "label": "Nutrition Adherence"},
    "workout_rating": {"type": "abs", "threshold": 3.0, "label": "Workout Rating"},
    "stress_level": {"type": "abs", "threshold": 3.0, "label": "Stress Level"},
    "energy_level": {"type": "abs", "threshold": 3.0, "label": "Energy Level"},
    "mood_wellbeing": {"type": "abs", "threshold": 3.0, "label": "Mood & Wellbeing"},
    # Water intake — percentage change
    "water_intake": {"type": "pct", "threshold": 50.0, "label": "Water Intake"},
}


def parse_thresholds(
    weight_pct: float = 20.0,
    body_pct: float = 15.0,
    lifestyle_abs: float = 3.0,
) -> dict[str, dict[str, Any]]:
    """Build thresholds dict from config values.

    Args:
        weight_pct: Percentage change threshold for weight.
        body_pct: Percentage change threshold for body measurements.
        lifestyle_abs: Absolute change threshold for lifestyle ratings.

    Returns:
        Thresholds dict keyed by metric name.
    """
    thresholds = dict(DEFAULT_THRESHOLDS)

    # Override weight threshold
    thresholds["weight"] = {**thresholds["weight"], "threshold": weight_pct}

    # Override body measurement thresholds
    for metric in ("waist", "hips", "biceps", "thighs"):
        thresholds[metric] = {**thresholds[metric], "threshold": body_pct}

    # Override lifestyle thresholds
    for metric in LIFESTYLE_METRICS:
        thresholds[metric] = {**thresholds[metric], "threshold": lifestyle_abs}

    return thresholds


def detect_anomalies(
    data_points: list[dict[str, Any]],
    metric: str,
    thresholds: dict[str, dict[str, Any]] | None = None,
    window_days: int = 7,
) -> list[dict[str, Any]]:
    """Detect anomalies in a timeseries of metric values.

    Compares each data point to its predecessor within the lookback
    window and flags values that exceed the configured threshold.

    Args:
        data_points: List of dicts with 'date' (str/datetime) and 'value' (numeric).
                     Must be sorted chronologically (oldest first).
        metric: The metric name (e.g. 'weight', 'sleep_quality').
        thresholds: Threshold config dict. Uses DEFAULT_THRESHOLDS if None.
        window_days: Only compare points within this many days of each other.

    Returns:
        List of anomaly dicts with keys:
            date, value, previous, change, pct_change, severity, message
    """
    if not data_points or len(data_points) < 2:
        return []

    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS

    config = thresholds.get(metric)
    if not config:
        return []

    threshold_type = config["type"]
    threshold_value = config["threshold"]
    label = config.get("label", metric)

    anomalies: list[dict[str, Any]] = []

    for i in range(1, len(data_points)):
        current = data_points[i]
        previous = data_points[i - 1]

        current_val = _to_float(current.get("value"))
        previous_val = _to_float(previous.get("value"))

        if current_val is None or previous_val is None:
            continue

        # Check window
        current_date = _parse_date(current.get("date"))
        previous_date = _parse_date(previous.get("date"))
        if current_date and previous_date:
            delta = (current_date - previous_date).days
            if delta > window_days:
                continue

        change = current_val - previous_val
        abs_change = abs(change)

        # Calculate percentage change (guard against zero division)
        pct_change = (abs_change / abs(previous_val) * 100) if previous_val != 0 else 0.0

        is_anomaly = (threshold_type == "pct" and pct_change >= threshold_value) or (
            threshold_type == "abs" and abs_change >= threshold_value
        )

        if is_anomaly:
            direction = "increased" if change > 0 else "decreased"
            if threshold_type == "pct":
                message = (
                    f"{label} {direction} by {pct_change:.1f}% ({previous_val} -> {current_val})"
                )
            else:
                message = (
                    f"{label} {direction} by {abs_change:.1f} points "
                    f"({previous_val} -> {current_val})"
                )

            severity = _classify_severity(threshold_type, pct_change, abs_change, threshold_value)

            anomalies.append(
                {
                    "date": str(current.get("date", "")),
                    "value": current_val,
                    "previous": previous_val,
                    "change": round(change, 2),
                    "pct_change": round(pct_change, 2),
                    "severity": severity,
                    "metric": metric,
                    "message": message,
                }
            )

    return anomalies


def check_minimum_thresholds(
    data_points: list[dict[str, Any]],
    sleep_minimum: float = 7.0,
    step_minimum: int = 5000,
) -> list[dict[str, Any]]:
    """Check if recent values fall below absolute minimum thresholds.

    Unlike detect_anomalies which compares consecutive points, this
    checks each point against a fixed floor value.

    Args:
        data_points: List of dicts with 'date', 'value', and 'metric' keys.
        sleep_minimum: Minimum acceptable sleep quality score.
        step_minimum: Minimum acceptable daily step count.

    Returns:
        List of warning dicts.
    """
    warnings: list[dict[str, Any]] = []

    for point in data_points:
        metric = point.get("metric", "")
        value = _to_float(point.get("value"))
        if value is None:
            continue

        if metric == "sleep_quality" and value < sleep_minimum:
            warnings.append(
                {
                    "date": str(point.get("date", "")),
                    "metric": "sleep_quality",
                    "value": value,
                    "threshold": sleep_minimum,
                    "severity": "warning",
                    "message": f"Sleep quality ({value}) below minimum ({sleep_minimum})",
                }
            )
        elif metric == "steps" and value < step_minimum:
            warnings.append(
                {
                    "date": str(point.get("date", "")),
                    "metric": "steps",
                    "value": value,
                    "threshold": step_minimum,
                    "severity": "warning",
                    "message": f"Step count ({int(value)}) below minimum ({step_minimum})",
                }
            )

    return warnings


def scan_client_anomalies(
    checkins: list[dict[str, Any]],
    thresholds: dict[str, dict[str, Any]] | None = None,
    window_days: int = 7,
    sleep_minimum: float = 7.0,
    step_minimum: int = 5000,
) -> dict[str, list[dict[str, Any]]]:
    """Scan all check-in fields for anomalies across a client's history.

    Args:
        checkins: List of parsed check-in dicts. Each must have a 'date' key
                  and metric keys (weight, sleep_quality, etc.).
        thresholds: Override thresholds. Uses DEFAULT_THRESHOLDS if None.
        window_days: Lookback window for anomaly detection.
        sleep_minimum: Minimum sleep quality to flag.
        step_minimum: Minimum step count to flag.

    Returns:
        Dict keyed by metric name, each value a list of anomaly dicts.
        Only includes metrics that have anomalies.
    """
    if not checkins:
        return {}

    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS

    # Build per-metric timeseries from check-ins
    all_metrics = set(BODY_METRICS | LIFESTYLE_METRICS | {"water_intake"})
    timeseries: dict[str, list[dict[str, Any]]] = {m: [] for m in all_metrics}

    for checkin in checkins:
        date = checkin.get("date", checkin.get("submitted_at", ""))
        for metric in all_metrics:
            value = checkin.get(metric)
            if value is not None:
                parsed = _to_float(value)
                if parsed is not None:
                    timeseries[metric].append({"date": date, "value": parsed})

    # Detect anomalies per metric
    results: dict[str, list[dict[str, Any]]] = {}
    for metric, points in timeseries.items():
        if len(points) < 2:
            continue
        anomalies = detect_anomalies(points, metric, thresholds, window_days)
        if anomalies:
            results[metric] = anomalies

    # Check minimum thresholds for sleep
    sleep_points = timeseries.get("sleep_quality", [])
    if sleep_points:
        sleep_data = [
            {"date": p["date"], "value": p["value"], "metric": "sleep_quality"}
            for p in sleep_points
        ]
        sleep_warnings = check_minimum_thresholds(
            sleep_data,
            sleep_minimum=sleep_minimum,
        )
        if sleep_warnings:
            results.setdefault("sleep_quality_minimum", []).extend(sleep_warnings)

    return results


def _to_float(value: Any) -> float | None:
    """Safely convert a value to float."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _parse_date(value: Any) -> datetime | None:
    """Parse a date string or return datetime as-is."""
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    date_str = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _classify_severity(
    threshold_type: str,
    pct_change: float,
    abs_change: float,
    threshold: float,
) -> str:
    """Classify anomaly severity based on how far it exceeds the threshold."""
    if threshold_type == "pct":
        ratio = pct_change / threshold if threshold > 0 else 1.0
    else:
        ratio = abs_change / threshold if threshold > 0 else 1.0

    if ratio >= 2.0:
        return "critical"
    if ratio >= 1.5:
        return "high"
    return "warning"

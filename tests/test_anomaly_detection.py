"""Tests for the anomaly detection module."""

from __future__ import annotations

from kahunas_client.anomaly_detection import (
    BODY_METRICS,
    DEFAULT_THRESHOLDS,
    LIFESTYLE_METRICS,
    check_minimum_thresholds,
    detect_anomalies,
    parse_thresholds,
    scan_client_anomalies,
)

# ── DEFAULT_THRESHOLDS ──


class TestDefaultThresholds:
    """Tests for the default threshold configuration."""

    def test_all_body_metrics_have_thresholds(self) -> None:
        for metric in BODY_METRICS:
            assert metric in DEFAULT_THRESHOLDS

    def test_all_lifestyle_metrics_have_thresholds(self) -> None:
        for metric in LIFESTYLE_METRICS:
            assert metric in DEFAULT_THRESHOLDS

    def test_water_intake_has_threshold(self) -> None:
        assert "water_intake" in DEFAULT_THRESHOLDS

    def test_body_metrics_use_pct_type(self) -> None:
        for metric in BODY_METRICS:
            assert DEFAULT_THRESHOLDS[metric]["type"] == "pct"

    def test_lifestyle_metrics_use_abs_type(self) -> None:
        for metric in LIFESTYLE_METRICS:
            assert DEFAULT_THRESHOLDS[metric]["type"] == "abs"

    def test_all_have_labels(self) -> None:
        for metric, config in DEFAULT_THRESHOLDS.items():
            assert "label" in config, f"Missing label for {metric}"

    def test_reasonable_weight_threshold(self) -> None:
        assert DEFAULT_THRESHOLDS["weight"]["threshold"] == 20.0

    def test_reasonable_lifestyle_threshold(self) -> None:
        assert DEFAULT_THRESHOLDS["sleep_quality"]["threshold"] == 3.0

    def test_water_intake_pct_type(self) -> None:
        assert DEFAULT_THRESHOLDS["water_intake"]["type"] == "pct"


# ── parse_thresholds ──


class TestParseThresholds:
    """Tests for building thresholds from config values."""

    def test_default_values(self) -> None:
        thresholds = parse_thresholds()
        assert thresholds["weight"]["threshold"] == 20.0
        assert thresholds["waist"]["threshold"] == 15.0
        assert thresholds["sleep_quality"]["threshold"] == 3.0

    def test_custom_weight_pct(self) -> None:
        thresholds = parse_thresholds(weight_pct=10.0)
        assert thresholds["weight"]["threshold"] == 10.0
        # Body metrics should not be affected
        assert thresholds["waist"]["threshold"] == 15.0

    def test_custom_body_pct(self) -> None:
        thresholds = parse_thresholds(body_pct=25.0)
        assert thresholds["waist"]["threshold"] == 25.0
        assert thresholds["hips"]["threshold"] == 25.0
        assert thresholds["biceps"]["threshold"] == 25.0
        assert thresholds["thighs"]["threshold"] == 25.0

    def test_custom_lifestyle_abs(self) -> None:
        thresholds = parse_thresholds(lifestyle_abs=5.0)
        assert thresholds["sleep_quality"]["threshold"] == 5.0
        assert thresholds["stress_level"]["threshold"] == 5.0

    def test_preserves_type_field(self) -> None:
        thresholds = parse_thresholds(weight_pct=30.0)
        assert thresholds["weight"]["type"] == "pct"

    def test_preserves_label_field(self) -> None:
        thresholds = parse_thresholds()
        assert thresholds["weight"]["label"] == "Weight"


# ── detect_anomalies ──


class TestDetectAnomalies:
    """Tests for anomaly detection on timeseries data."""

    def test_empty_data(self) -> None:
        assert detect_anomalies([], "weight") == []

    def test_single_point(self) -> None:
        assert detect_anomalies([{"date": "2025-01-01", "value": 80}], "weight") == []

    def test_no_anomaly_small_change(self) -> None:
        data = [
            {"date": "2025-01-01", "value": 80.0},
            {"date": "2025-01-07", "value": 81.0},
        ]
        result = detect_anomalies(data, "weight")
        assert result == []

    def test_detects_large_weight_drop(self) -> None:
        data = [
            {"date": "2025-01-01", "value": 100.0},
            {"date": "2025-01-07", "value": 75.0},
        ]
        result = detect_anomalies(data, "weight")
        assert len(result) == 1
        assert result[0]["value"] == 75.0
        assert result[0]["previous"] == 100.0
        assert "decreased" in result[0]["message"]

    def test_detects_large_weight_gain(self) -> None:
        data = [
            {"date": "2025-01-01", "value": 80.0},
            {"date": "2025-01-07", "value": 100.0},
        ]
        result = detect_anomalies(data, "weight")
        assert len(result) == 1
        assert "increased" in result[0]["message"]

    def test_respects_window_days(self) -> None:
        data = [
            {"date": "2025-01-01", "value": 100.0},
            {"date": "2025-02-01", "value": 75.0},  # 31 days apart
        ]
        result = detect_anomalies(data, "weight", window_days=7)
        assert result == []

    def test_within_window_days(self) -> None:
        data = [
            {"date": "2025-01-01", "value": 100.0},
            {"date": "2025-01-06", "value": 75.0},  # 5 days apart
        ]
        result = detect_anomalies(data, "weight", window_days=7)
        assert len(result) == 1

    def test_lifestyle_abs_threshold(self) -> None:
        data = [
            {"date": "2025-01-01", "value": 8.0},
            {"date": "2025-01-07", "value": 4.0},  # Drop of 4 points
        ]
        result = detect_anomalies(data, "sleep_quality")
        assert len(result) == 1
        assert "points" in result[0]["message"]

    def test_lifestyle_no_anomaly_small_change(self) -> None:
        data = [
            {"date": "2025-01-01", "value": 7.0},
            {"date": "2025-01-07", "value": 6.0},  # Drop of 1 point
        ]
        result = detect_anomalies(data, "sleep_quality")
        assert result == []

    def test_custom_thresholds(self) -> None:
        custom = {"weight": {"type": "pct", "threshold": 5.0, "label": "Weight"}}
        data = [
            {"date": "2025-01-01", "value": 100.0},
            {"date": "2025-01-07", "value": 93.0},  # 7% drop
        ]
        result = detect_anomalies(data, "weight", thresholds=custom)
        assert len(result) == 1

    def test_unknown_metric_returns_empty(self) -> None:
        data = [
            {"date": "2025-01-01", "value": 100},
            {"date": "2025-01-07", "value": 50},
        ]
        result = detect_anomalies(data, "unknown_metric")
        assert result == []

    def test_severity_warning(self) -> None:
        data = [
            {"date": "2025-01-01", "value": 100.0},
            {"date": "2025-01-07", "value": 78.0},  # 22% drop, just above threshold
        ]
        result = detect_anomalies(data, "weight")
        assert result[0]["severity"] == "warning"

    def test_severity_high(self) -> None:
        data = [
            {"date": "2025-01-01", "value": 100.0},
            {"date": "2025-01-07", "value": 68.0},  # 32% drop, 1.6x threshold
        ]
        result = detect_anomalies(data, "weight")
        assert result[0]["severity"] == "high"

    def test_severity_critical(self) -> None:
        data = [
            {"date": "2025-01-01", "value": 100.0},
            {"date": "2025-01-07", "value": 55.0},  # 45% drop, 2.25x threshold
        ]
        result = detect_anomalies(data, "weight")
        assert result[0]["severity"] == "critical"

    def test_multiple_anomalies_in_series(self) -> None:
        data = [
            {"date": "2025-01-01", "value": 100.0},
            {"date": "2025-01-03", "value": 75.0},
            {"date": "2025-01-05", "value": 55.0},
        ]
        result = detect_anomalies(data, "weight")
        assert len(result) == 2

    def test_none_values_skipped(self) -> None:
        data = [
            {"date": "2025-01-01", "value": 100.0},
            {"date": "2025-01-03", "value": None},
            {"date": "2025-01-05", "value": 75.0},
        ]
        result = detect_anomalies(data, "weight")
        assert len(result) == 0  # Can't compare to None

    def test_string_values_parsed(self) -> None:
        data = [
            {"date": "2025-01-01", "value": "100.0"},
            {"date": "2025-01-07", "value": "75.0"},
        ]
        result = detect_anomalies(data, "weight")
        assert len(result) == 1

    def test_zero_previous_value(self) -> None:
        data = [
            {"date": "2025-01-01", "value": 0.0},
            {"date": "2025-01-07", "value": 80.0},
        ]
        # Should not crash on division by zero
        result = detect_anomalies(data, "weight")
        assert isinstance(result, list)

    def test_result_fields(self) -> None:
        data = [
            {"date": "2025-01-01", "value": 100.0},
            {"date": "2025-01-07", "value": 75.0},
        ]
        result = detect_anomalies(data, "weight")
        anomaly = result[0]
        assert "date" in anomaly
        assert "value" in anomaly
        assert "previous" in anomaly
        assert "change" in anomaly
        assert "pct_change" in anomaly
        assert "severity" in anomaly
        assert "metric" in anomaly
        assert "message" in anomaly


# ── check_minimum_thresholds ──


class TestCheckMinimumThresholds:
    """Tests for absolute minimum threshold checks."""

    def test_sleep_below_minimum(self) -> None:
        data = [{"date": "2025-01-01", "value": 5.0, "metric": "sleep_quality"}]
        result = check_minimum_thresholds(data, sleep_minimum=7.0)
        assert len(result) == 1
        assert result[0]["metric"] == "sleep_quality"

    def test_sleep_above_minimum(self) -> None:
        data = [{"date": "2025-01-01", "value": 8.0, "metric": "sleep_quality"}]
        result = check_minimum_thresholds(data, sleep_minimum=7.0)
        assert result == []

    def test_steps_below_minimum(self) -> None:
        data = [{"date": "2025-01-01", "value": 3000, "metric": "steps"}]
        result = check_minimum_thresholds(data, step_minimum=5000)
        assert len(result) == 1

    def test_steps_above_minimum(self) -> None:
        data = [{"date": "2025-01-01", "value": 8000, "metric": "steps"}]
        result = check_minimum_thresholds(data, step_minimum=5000)
        assert result == []

    def test_mixed_metrics(self) -> None:
        data = [
            {"date": "2025-01-01", "value": 5.0, "metric": "sleep_quality"},
            {"date": "2025-01-01", "value": 3000, "metric": "steps"},
        ]
        result = check_minimum_thresholds(data, sleep_minimum=7.0, step_minimum=5000)
        assert len(result) == 2

    def test_none_value_skipped(self) -> None:
        data = [{"date": "2025-01-01", "value": None, "metric": "sleep_quality"}]
        result = check_minimum_thresholds(data)
        assert result == []


# ── scan_client_anomalies ──


class TestScanClientAnomalies:
    """Tests for full-client anomaly scanning."""

    def test_empty_checkins(self) -> None:
        assert scan_client_anomalies([]) == {}

    def test_single_checkin(self) -> None:
        checkins = [{"date": "2025-01-01", "weight": 80.0}]
        assert scan_client_anomalies(checkins) == {}

    def test_detects_weight_anomaly(self) -> None:
        checkins = [
            {"date": "2025-01-01", "weight": 100.0, "sleep_quality": 8},
            {"date": "2025-01-07", "weight": 75.0, "sleep_quality": 7},
        ]
        result = scan_client_anomalies(checkins)
        assert "weight" in result

    def test_no_anomaly_stable_data(self) -> None:
        checkins = [
            {"date": "2025-01-01", "weight": 80.0, "sleep_quality": 8},
            {"date": "2025-01-07", "weight": 80.5, "sleep_quality": 7.5},
        ]
        result = scan_client_anomalies(checkins)
        # Should have no weight or sleep anomalies
        assert "weight" not in result

    def test_detects_sleep_minimum_warning(self) -> None:
        checkins = [
            {"date": "2025-01-01", "sleep_quality": 5.0},
            {"date": "2025-01-07", "sleep_quality": 4.0},
        ]
        result = scan_client_anomalies(checkins, sleep_minimum=7.0)
        assert "sleep_quality_minimum" in result

    def test_multiple_metrics_anomalies(self) -> None:
        checkins = [
            {"date": "2025-01-01", "weight": 100.0, "waist": 90.0},
            {"date": "2025-01-07", "weight": 75.0, "waist": 70.0},
        ]
        result = scan_client_anomalies(checkins)
        assert "weight" in result
        assert "waist" in result

    def test_uses_submitted_at_fallback(self) -> None:
        checkins = [
            {"submitted_at": "2025-01-01", "weight": 100.0},
            {"submitted_at": "2025-01-07", "weight": 75.0},
        ]
        result = scan_client_anomalies(checkins)
        assert "weight" in result

    def test_custom_thresholds(self) -> None:
        thresholds = parse_thresholds(weight_pct=5.0)
        checkins = [
            {"date": "2025-01-01", "weight": 100.0},
            {"date": "2025-01-07", "weight": 93.0},  # 7% — above 5% custom threshold
        ]
        result = scan_client_anomalies(checkins, thresholds=thresholds)
        assert "weight" in result

    def test_string_values_handled(self) -> None:
        checkins = [
            {"date": "2025-01-01", "weight": "100.0"},
            {"date": "2025-01-07", "weight": "75.0"},
        ]
        result = scan_client_anomalies(checkins)
        assert "weight" in result

    def test_none_values_ignored(self) -> None:
        checkins = [
            {"date": "2025-01-01", "weight": None},
            {"date": "2025-01-07", "weight": None},
        ]
        result = scan_client_anomalies(checkins)
        assert "weight" not in result

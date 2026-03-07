"""Tests for chart generation module."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from kahunas_client.charts import (
    METRIC_CONFIG,
    RANGE_LABELS,
    _parse_date,
    generate_chart,
)


class TestParseDate:
    """Test date parsing for various formats."""

    def test_iso_format(self) -> None:
        dt = _parse_date("2024-03-15")
        assert dt.year == 2024
        assert dt.month == 3
        assert dt.day == 15

    def test_iso_datetime(self) -> None:
        dt = _parse_date("2024-03-15 10:30:00")
        assert dt.year == 2024
        assert dt.hour == 10

    def test_uk_format(self) -> None:
        dt = _parse_date("15/03/2024")
        assert dt.day == 15
        assert dt.month == 3

    def test_named_month_format(self) -> None:
        dt = _parse_date("Mar 15, 2024")
        assert dt.month == 3
        assert dt.day == 15

    def test_full_month_format(self) -> None:
        dt = _parse_date("March 15, 2024")
        assert dt.month == 3

    def test_invalid_format(self) -> None:
        with pytest.raises(ValueError, match="Cannot parse"):
            _parse_date("not-a-date")


class TestGenerateChart:
    """Test chart generation."""

    def test_generates_png_bytes(self) -> None:
        data = [
            {"date": "2024-01-01", "value": 80.0},
            {"date": "2024-02-01", "value": 79.5},
            {"date": "2024-03-01", "value": 78.0},
        ]
        result = generate_chart(data, metric="weight")
        assert isinstance(result, bytes)
        assert len(result) > 0
        # PNG magic bytes
        assert result[:4] == b"\x89PNG"

    def test_saves_to_file(self) -> None:
        data = [
            {"date": "2024-01-01", "value": 80.0},
            {"date": "2024-02-01", "value": 79.5},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "test_chart.png")
            generate_chart(data, metric="weight", output_path=path)
            assert Path(path).exists()
            assert Path(path).stat().st_size > 0

    def test_empty_data_generates_placeholder(self) -> None:
        result = generate_chart([], metric="weight")
        assert isinstance(result, bytes)
        assert result[:4] == b"\x89PNG"

    def test_single_point(self) -> None:
        data = [{"date": "2024-01-01", "value": 80.0}]
        result = generate_chart(data, metric="weight")
        assert isinstance(result, bytes)
        assert result[:4] == b"\x89PNG"

    def test_bodyfat_metric(self) -> None:
        data = [
            {"date": "2024-01-01", "value": 20.0},
            {"date": "2024-06-01", "value": 15.5},
        ]
        result = generate_chart(data, metric="bodyfat")
        assert isinstance(result, bytes)

    def test_steps_metric(self) -> None:
        data = [
            {"date": "2024-01-01", "value": 8000},
            {"date": "2024-01-02", "value": 10500},
            {"date": "2024-01-03", "value": 7200},
        ]
        result = generate_chart(data, metric="steps", time_range="week")
        assert isinstance(result, bytes)

    def test_client_name_in_title(self) -> None:
        data = [
            {"date": "2024-01-01", "value": 80.0},
            {"date": "2024-02-01", "value": 79.0},
        ]
        # Just verify it doesn't crash with client name
        result = generate_chart(data, metric="weight", client_name="John Doe")
        assert isinstance(result, bytes)

    def test_custom_title(self) -> None:
        data = [
            {"date": "2024-01-01", "value": 80.0},
            {"date": "2024-02-01", "value": 79.0},
        ]
        result = generate_chart(data, metric="weight", title="My Custom Chart")
        assert isinstance(result, bytes)

    def test_skips_invalid_data_points(self) -> None:
        data = [
            {"date": "2024-01-01", "value": 80.0},
            {"date": "bad-date", "value": 79.0},  # should be skipped
            {"date": "2024-03-01", "value": 78.0},
        ]
        result = generate_chart(data, metric="weight")
        assert isinstance(result, bytes)

    def test_alternative_data_keys(self) -> None:
        """Test data points using 'label' and 'y' keys."""
        data = [
            {"label": "2024-01-01", "y": 80.0},
            {"label": "2024-02-01", "y": 79.0},
        ]
        result = generate_chart(data, metric="weight")
        assert isinstance(result, bytes)

    def test_sorts_by_date(self) -> None:
        data = [
            {"date": "2024-03-01", "value": 78.0},
            {"date": "2024-01-01", "value": 80.0},
            {"date": "2024-02-01", "value": 79.0},
        ]
        result = generate_chart(data, metric="weight")
        assert isinstance(result, bytes)

    def test_all_time_ranges(self) -> None:
        data = [
            {"date": "2024-01-01", "value": 80.0},
            {"date": "2024-06-01", "value": 75.0},
        ]
        for range_key in RANGE_LABELS:
            result = generate_chart(data, metric="weight", time_range=range_key)
            assert isinstance(result, bytes)

    def test_all_metric_types(self) -> None:
        data = [
            {"date": "2024-01-01", "value": 50.0},
            {"date": "2024-02-01", "value": 55.0},
        ]
        for metric_key in METRIC_CONFIG:
            result = generate_chart(data, metric=metric_key)
            assert isinstance(result, bytes)

    def test_unknown_metric_uses_defaults(self) -> None:
        data = [
            {"date": "2024-01-01", "value": 10.0},
            {"date": "2024-02-01", "value": 12.0},
        ]
        result = generate_chart(data, metric="custom_metric")
        assert isinstance(result, bytes)

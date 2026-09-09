"""Regression tests for ordering and threshold defects.

Each test here corresponds to a defect where the code produced a confidently
wrong answer rather than failing: a client's progress direction was inverted,
or a configured threshold was silently ignored. These are the failure modes
that reach a coach as advice about a real person, so they are pinned
explicitly.
"""

from __future__ import annotations

from typing import Any

import pytest

from kahunas_client.anomaly_detection import scan_client_anomalies
from kahunas_client.checkin_history import format_checkin_summary


def _weight_checkins() -> list[dict[str, Any]]:
    """A client who lost 10 kg between January and June."""
    return [
        {"check_in_number": 1, "submitted_at": "2024-01-01", "weight": "90"},
        {"check_in_number": 2, "submitted_at": "2024-06-01", "weight": "80"},
    ]


class TestCheckinSummaryOrdering:
    """format_checkin_summary sorted by check-in number, not by date."""

    def test_latest_and_first_are_the_right_way_round(self) -> None:
        summary = format_checkin_summary(_weight_checkins())
        assert summary["first_checkin"] == "2024-01-01"
        assert summary["latest_checkin"] == "2024-06-01"

    def test_weight_loss_is_not_reported_as_a_gain(self) -> None:
        """The defect reported a 10 kg loss as "+10.0, direction up"."""
        summary = format_checkin_summary(_weight_checkins())
        assert summary["trends"]["weight"] == {"change": -10.0, "direction": "down"}

    def test_a_missing_check_in_number_does_not_reorder_history(self) -> None:
        """A missing number defaulted to 0 and sorted a recent check-in last."""
        checkins = [
            {"check_in_number": 1, "submitted_at": "2024-01-01", "weight": "90"},
            {"submitted_at": "2024-06-01", "weight": "80"},
        ]
        summary = format_checkin_summary(checkins)
        assert summary["latest_checkin"] == "2024-06-01"
        assert summary["trends"]["weight"]["direction"] == "down"

    def test_numbers_disagreeing_with_dates_follow_the_dates(self) -> None:
        checkins = [
            {"check_in_number": 9, "submitted_at": "2024-01-01", "weight": "90"},
            {"check_in_number": 2, "submitted_at": "2024-06-01", "weight": "80"},
        ]
        summary = format_checkin_summary(checkins)
        assert summary["latest_checkin"] == "2024-06-01"
        assert summary["trends"]["weight"]["direction"] == "down"

    def test_an_unparseable_date_cannot_become_the_latest_checkin(self) -> None:
        checkins = [
            {"check_in_number": 1, "submitted_at": "not a date", "weight": "95"},
            {"check_in_number": 2, "submitted_at": "2024-06-01", "weight": "80"},
        ]
        summary = format_checkin_summary(checkins)
        assert summary["latest_checkin"] == "2024-06-01"

    def test_input_order_does_not_change_the_result(self) -> None:
        forwards = format_checkin_summary(_weight_checkins())
        backwards = format_checkin_summary(list(reversed(_weight_checkins())))
        assert forwards["trends"] == backwards["trends"]
        assert forwards["latest_checkin"] == backwards["latest_checkin"]


class TestAnomalyOrdering:
    """detect_anomalies requires chronological input; nothing enforced it."""

    @staticmethod
    def _steady_loss() -> list[dict[str, Any]]:
        """Three readings, each a 15% drop, all within the 20% threshold."""
        return [
            {"submitted_at": "2024-01-01", "weight": 100},
            {"submitted_at": "2024-02-01", "weight": 85},
            {"submitted_at": "2024-03-01", "weight": 70},
        ]

    @pytest.mark.parametrize("reverse", [False, True])
    def test_within_threshold_changes_raise_nothing_in_either_order(self, reverse: bool) -> None:
        """Reversed input previously produced a spurious "increased" anomaly."""
        data = list(reversed(self._steady_loss())) if reverse else self._steady_loss()
        result = scan_client_anomalies(data, window_days=400)
        assert result.get("weight", []) == []

    def test_a_real_change_is_detected_in_any_input_order(self) -> None:
        data = [
            {"submitted_at": "2024-01-01", "weight": 100},
            {"submitted_at": "2024-02-01", "weight": 70},
        ]
        forwards = scan_client_anomalies(data, window_days=400)["weight"]
        backwards = scan_client_anomalies(list(reversed(data)), window_days=400)["weight"]
        assert len(forwards) == len(backwards) == 1
        assert forwards[0]["message"] == backwards[0]["message"]

    def test_weight_loss_is_never_described_as_an_increase(self) -> None:
        data = [
            {"submitted_at": "2024-01-01", "weight": 100},
            {"submitted_at": "2024-02-01", "weight": 70},
        ]
        for ordering in (data, list(reversed(data))):
            for anomaly in scan_client_anomalies(ordering, window_days=400)["weight"]:
                assert "decreased" in anomaly["message"]
                assert "increased" not in anomaly["message"]

    def test_shuffled_input_matches_chronological_input(self) -> None:
        chronological = self._steady_loss()
        shuffled = [chronological[2], chronological[0], chronological[1]]
        assert scan_client_anomalies(shuffled, window_days=400) == scan_client_anomalies(
            chronological, window_days=400
        )


class TestStepMinimum:
    """step_minimum was accepted and documented but never applied."""

    def test_step_counts_below_the_minimum_are_reported(self) -> None:
        result = scan_client_anomalies(
            [
                {"submitted_at": "2024-01-01", "steps": 500},
                {"submitted_at": "2024-01-02", "steps": 400},
            ],
            step_minimum=5000,
            window_days=400,
        )
        warnings = result.get("steps_minimum", [])
        assert len(warnings) == 2
        assert all("below minimum" in w["message"] for w in warnings)

    def test_healthy_step_counts_are_not_reported(self) -> None:
        result = scan_client_anomalies(
            [
                {"submitted_at": "2024-01-01", "steps": 9000},
                {"submitted_at": "2024-01-02", "steps": 9500},
            ],
            step_minimum=5000,
            window_days=400,
        )
        assert result.get("steps_minimum", []) == []

    def test_the_configured_threshold_is_honoured(self) -> None:
        """A caller raising the bar must get warnings the default would not."""
        checkins = [
            {"submitted_at": "2024-01-01", "steps": 7000},
            {"submitted_at": "2024-01-02", "steps": 7200},
        ]
        assert (
            scan_client_anomalies(checkins, step_minimum=5000, window_days=400).get(
                "steps_minimum", []
            )
            == []
        )
        assert (
            len(
                scan_client_anomalies(checkins, step_minimum=10000, window_days=400).get(
                    "steps_minimum", []
                )
            )
            == 2
        )

    def test_sleep_minimum_still_works_alongside_steps(self) -> None:
        result = scan_client_anomalies(
            [
                {"submitted_at": "2024-01-01", "sleep_quality": 4, "steps": 100},
                {"submitted_at": "2024-01-02", "sleep_quality": 3, "steps": 200},
            ],
            sleep_minimum=7.0,
            step_minimum=5000,
            window_days=400,
        )
        assert result.get("sleep_quality_minimum")
        assert result.get("steps_minimum")

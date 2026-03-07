"""Tests for the PDF export module."""

from __future__ import annotations

from pathlib import Path

from kahunas_client.pdf_export import (
    PDFExporter,
    export_checkin_summary_pdf,
    export_workout_plan_pdf,
    export_workout_program_pdf,
)

# ── PDFExporter ──


class TestPDFExporter:
    """Tests for the PDFExporter class."""

    def test_creates_pdf(self, tmp_path: Path) -> None:
        pdf = PDFExporter(title="Test")
        pdf.alias_nb_pages()
        pdf.add_page()
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 10, "Hello World")
        out = tmp_path / "test.pdf"
        pdf.output(str(out))
        assert out.exists()
        assert out.stat().st_size > 0

    def test_header_rendered(self, tmp_path: Path) -> None:
        pdf = PDFExporter(title="My Title")
        pdf.alias_nb_pages()
        pdf.add_page()
        out = tmp_path / "header.pdf"
        pdf.output(str(out))
        assert out.exists()

    def test_section_title(self, tmp_path: Path) -> None:
        pdf = PDFExporter(title="Sections")
        pdf.alias_nb_pages()
        pdf.add_page()
        pdf.add_section_title("Section One")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 10, "Content here")
        out = tmp_path / "sections.pdf"
        pdf.output(str(out))
        assert out.exists()

    def test_table_rendering(self, tmp_path: Path) -> None:
        pdf = PDFExporter(title="Table")
        pdf.alias_nb_pages()
        pdf.add_page()
        headers = ["Name", "Value"]
        rows = [["Weight", "80"], ["Height", "180"]]
        pdf.add_table(headers, rows)
        out = tmp_path / "table.pdf"
        pdf.output(str(out))
        assert out.exists()

    def test_table_empty_headers(self, tmp_path: Path) -> None:
        pdf = PDFExporter(title="Empty")
        pdf.alias_nb_pages()
        pdf.add_page()
        pdf.add_table([], [])  # Should not crash
        out = tmp_path / "empty_table.pdf"
        pdf.output(str(out))
        assert out.exists()

    def test_table_custom_widths(self, tmp_path: Path) -> None:
        pdf = PDFExporter(title="Custom")
        pdf.alias_nb_pages()
        pdf.add_page()
        pdf.add_table(["A", "B"], [["1", "2"]], col_widths=[50.0, 50.0])
        out = tmp_path / "custom.pdf"
        pdf.output(str(out))
        assert out.exists()

    def test_long_text_truncated(self, tmp_path: Path) -> None:
        pdf = PDFExporter(title="Long")
        pdf.alias_nb_pages()
        pdf.add_page()
        long_text = "x" * 100
        pdf.add_table(["Col"], [[long_text]])
        out = tmp_path / "long.pdf"
        pdf.output(str(out))
        assert out.exists()


# ── export_workout_program_pdf ──


class TestExportWorkoutProgramPDF:
    """Tests for workout program PDF export."""

    def test_basic_export(self, tmp_path: Path) -> None:
        program = {
            "name": "Push/Pull/Legs",
            "description": "A classic 3-day split",
            "days": [
                {
                    "name": "Day 1 - Push",
                    "exercises": [
                        {
                            "name": "Bench Press",
                            "sets": "4",
                            "reps": "8",
                            "rest": "90s",
                            "tempo": "3010",
                        },
                        {"name": "OHP", "sets": "3", "reps": "10", "rest": "60s", "tempo": "2010"},
                    ],
                },
                {
                    "name": "Day 2 - Pull",
                    "exercises": [
                        {
                            "name": "Deadlift",
                            "sets": "5",
                            "reps": "5",
                            "rest": "120s",
                            "tempo": "2010",
                        },
                    ],
                },
            ],
        }
        out = tmp_path / "program.pdf"
        result = export_workout_program_pdf(program, out)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 0

    def test_rest_day(self, tmp_path: Path) -> None:
        program = {
            "name": "Rest Program",
            "days": [{"name": "Day 3 - Rest", "exercises": []}],
        }
        out = tmp_path / "rest.pdf"
        result = export_workout_program_pdf(program, out)
        assert result.exists()

    def test_no_description(self, tmp_path: Path) -> None:
        program = {
            "name": "Minimal",
            "days": [
                {
                    "name": "Day 1",
                    "exercises": [
                        {"name": "Squats", "sets": "3", "reps": "10", "rest": "", "tempo": ""}
                    ],
                }
            ],
        }
        out = tmp_path / "minimal.pdf"
        result = export_workout_program_pdf(program, out)
        assert result.exists()

    def test_empty_days(self, tmp_path: Path) -> None:
        program = {"name": "Empty", "days": []}
        out = tmp_path / "empty.pdf"
        result = export_workout_program_pdf(program, out)
        assert result.exists()

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        out = tmp_path / "subdir" / "nested" / "program.pdf"
        program = {"name": "Test", "days": []}
        result = export_workout_program_pdf(program, out)
        assert result.exists()

    def test_workout_days_key(self, tmp_path: Path) -> None:
        """Test fallback to 'workout_days' key."""
        program = {
            "name": "Alt Key",
            "workout_days": [
                {
                    "name": "Day 1",
                    "exercises": [
                        {"name": "Push-ups", "sets": "3", "reps": "20", "rest": "", "tempo": ""}
                    ],
                }
            ],
        }
        out = tmp_path / "alt.pdf"
        result = export_workout_program_pdf(program, out)
        assert result.exists()

    def test_valid_pdf_header(self, tmp_path: Path) -> None:
        program = {"name": "Header Check", "days": []}
        out = tmp_path / "header_check.pdf"
        export_workout_program_pdf(program, out)
        content = out.read_bytes()
        assert content[:5] == b"%PDF-"


# ── export_checkin_summary_pdf ──


class TestExportCheckinSummaryPDF:
    """Tests for check-in summary PDF export."""

    def test_basic_export(self, tmp_path: Path) -> None:
        summary = {
            "client_name": "Alice Smith",
            "checkins": [
                {
                    "date": "2025-01-01",
                    "weight": 75.5,
                    "waist": 80,
                    "hips": 95,
                    "biceps": 32,
                    "thighs": 55,
                    "sleep_quality": 8,
                    "nutrition_adherence": 7,
                    "stress_level": 4,
                    "energy_level": 7,
                },
                {
                    "date": "2025-01-08",
                    "weight": 74.8,
                    "waist": 79,
                    "hips": 94,
                    "biceps": 32.5,
                    "thighs": 54.5,
                    "sleep_quality": 7,
                    "nutrition_adherence": 8,
                    "stress_level": 3,
                    "energy_level": 8,
                },
            ],
        }
        out = tmp_path / "checkin.pdf"
        result = export_checkin_summary_pdf(summary, out)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_no_checkins(self, tmp_path: Path) -> None:
        summary = {"client_name": "Bob", "checkins": []}
        out = tmp_path / "empty.pdf"
        result = export_checkin_summary_pdf(summary, out)
        assert result.exists()

    def test_with_trends(self, tmp_path: Path) -> None:
        summary = {
            "client_name": "Charlie",
            "checkins": [{"date": "2025-01-01", "weight": 80}],
            "trends": {
                "weight": {"direction": "down", "change": "-2.5kg"},
                "waist": "stable",
            },
        }
        out = tmp_path / "trends.pdf"
        result = export_checkin_summary_pdf(summary, out)
        assert result.exists()

    def test_units_kg_cm(self, tmp_path: Path) -> None:
        summary = {
            "client_name": "Diana",
            "checkins": [{"date": "2025-01-01", "weight": 65}],
        }
        out = tmp_path / "kg_cm.pdf"
        result = export_checkin_summary_pdf(summary, out, weight_unit="kg", measurement_unit="cm")
        assert result.exists()

    def test_units_lbs_inches(self, tmp_path: Path) -> None:
        summary = {
            "client_name": "Eve",
            "checkins": [{"date": "2025-01-01", "weight": 143}],
        }
        out = tmp_path / "lbs_inches.pdf"
        result = export_checkin_summary_pdf(
            summary, out, weight_unit="lbs", measurement_unit="inches"
        )
        assert result.exists()

    def test_missing_fields_show_dash(self, tmp_path: Path) -> None:
        summary = {
            "client_name": "Frank",
            "checkins": [{"date": "2025-01-01", "weight": None}],
        }
        out = tmp_path / "missing.pdf"
        result = export_checkin_summary_pdf(summary, out)
        assert result.exists()

    def test_valid_pdf_output(self, tmp_path: Path) -> None:
        summary = {
            "client_name": "Grace",
            "checkins": [{"date": "2025-01-01", "weight": 70}],
        }
        out = tmp_path / "valid.pdf"
        export_checkin_summary_pdf(summary, out)
        content = out.read_bytes()
        assert content[:5] == b"%PDF-"


# ── export_workout_plan_pdf ──


class TestExportWorkoutPlanPDF:
    """Tests for workout plan PDF export."""

    def test_basic_export(self, tmp_path: Path) -> None:
        plan = {
            "client_name": "Alice Smith",
            "plan_name": "Strength Builder",
            "notes": "Focus on compound movements",
            "days": [
                {
                    "name": "Monday - Upper",
                    "exercises": [
                        {
                            "name": "Bench Press",
                            "sets": "4",
                            "reps": "8",
                            "rest": "90s",
                            "tempo": "3010",
                            "notes": "Progressive overload",
                        },
                    ],
                },
                {
                    "name": "Tuesday - Rest",
                    "exercises": [],
                },
            ],
        }
        out = tmp_path / "plan.pdf"
        result = export_workout_plan_pdf(plan, out)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_no_notes(self, tmp_path: Path) -> None:
        plan = {
            "client_name": "Bob",
            "plan_name": "Quick Plan",
            "days": [
                {
                    "name": "Day 1",
                    "exercises": [
                        {
                            "name": "Squats",
                            "sets": "3",
                            "reps": "10",
                            "rest": "",
                            "tempo": "",
                            "notes": "",
                        }
                    ],
                }
            ],
        }
        out = tmp_path / "no_notes.pdf"
        result = export_workout_plan_pdf(plan, out)
        assert result.exists()

    def test_empty_days(self, tmp_path: Path) -> None:
        plan = {"client_name": "Charlie", "plan_name": "Empty", "days": []}
        out = tmp_path / "empty.pdf"
        result = export_workout_plan_pdf(plan, out)
        assert result.exists()

    def test_workout_days_key(self, tmp_path: Path) -> None:
        plan = {
            "client_name": "Diana",
            "name": "Alt Key Plan",
            "workout_days": [
                {
                    "name": "Day 1",
                    "exercises": [
                        {
                            "name": "Lunges",
                            "sets": "3",
                            "reps": "12",
                            "rest": "60s",
                            "tempo": "",
                            "notes": "",
                        }
                    ],
                }
            ],
        }
        out = tmp_path / "alt_key.pdf"
        result = export_workout_plan_pdf(plan, out)
        assert result.exists()

    def test_long_exercise_notes_truncated(self, tmp_path: Path) -> None:
        plan = {
            "client_name": "Eve",
            "plan_name": "Notes Test",
            "days": [
                {
                    "name": "Day 1",
                    "exercises": [
                        {
                            "name": "Ex1",
                            "sets": "3",
                            "reps": "10",
                            "rest": "",
                            "tempo": "",
                            "notes": "x" * 100,
                        },
                    ],
                },
            ],
        }
        out = tmp_path / "long_notes.pdf"
        result = export_workout_plan_pdf(plan, out)
        assert result.exists()

    def test_valid_pdf_output(self, tmp_path: Path) -> None:
        plan = {"client_name": "Frank", "plan_name": "Validate", "days": []}
        out = tmp_path / "valid.pdf"
        export_workout_plan_pdf(plan, out)
        content = out.read_bytes()
        assert content[:5] == b"%PDF-"

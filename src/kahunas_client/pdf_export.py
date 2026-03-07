"""PDF export for Kahunas workout programs, check-in summaries, and plans.

Uses fpdf2 for lightweight, pure-Python PDF generation. Produces
professional-looking documents with branded headers, tabular data,
and formatted text suitable for sharing with coaching clients.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fpdf import FPDF

logger = logging.getLogger(__name__)

# Default branding
_TITLE = "Kahunas"
_SUBTITLE = "Personal Training"
_MARGIN = 10
_CELL_HEIGHT = 7
_HEADER_HEIGHT = 10


class PDFExporter(FPDF):
    """Branded PDF exporter with Kahunas header and footer."""

    def __init__(self, title: str = "", orientation: str = "P") -> None:
        super().__init__(orientation=orientation, unit="mm", format="A4")
        self._doc_title = title
        self.set_auto_page_break(auto=True, margin=15)
        self.set_margins(_MARGIN, _MARGIN, _MARGIN)

    def header(self) -> None:
        """Render the page header with branding."""
        self.set_font("Helvetica", "B", 14)
        self.cell(0, 8, _TITLE, new_x="LMARGIN", new_y="NEXT")
        if self._doc_title:
            self.set_font("Helvetica", "", 10)
            self.cell(0, 5, self._doc_title, new_x="LMARGIN", new_y="NEXT")
        self.line(self.l_margin, self.get_y() + 1, self.w - self.r_margin, self.get_y() + 1)
        self.ln(5)

    def footer(self) -> None:
        """Render the page footer with page number."""
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    def add_section_title(self, text: str) -> None:
        """Add a bold section heading."""
        self.set_font("Helvetica", "B", 12)
        self.cell(0, _HEADER_HEIGHT, text, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def add_table(
        self,
        headers: list[str],
        rows: list[list[str]],
        col_widths: list[float] | None = None,
    ) -> None:
        """Render a table with header row and data rows.

        Args:
            headers: Column header labels.
            rows: List of row data (each row is a list of strings).
            col_widths: Optional column widths in mm. Auto-calculated if None.
        """
        if not headers:
            return

        usable_width = self.w - self.l_margin - self.r_margin
        if col_widths is None:
            col_widths = [usable_width / len(headers)] * len(headers)

        # Header row
        self.set_font("Helvetica", "B", 9)
        self.set_fill_color(51, 51, 51)
        self.set_text_color(255, 255, 255)
        for i, header in enumerate(headers):
            self.cell(col_widths[i], _CELL_HEIGHT, header, border=1, fill=True)
        self.ln()

        # Data rows
        self.set_font("Helvetica", "", 9)
        self.set_text_color(0, 0, 0)
        fill = False
        for row in rows:
            if fill:
                self.set_fill_color(240, 240, 240)
            else:
                self.set_fill_color(255, 255, 255)

            for i, cell_text in enumerate(row):
                w = col_widths[i] if i < len(col_widths) else col_widths[-1]
                # Truncate long text to fit cell
                display = cell_text[:40] if len(cell_text) > 40 else cell_text
                self.cell(w, _CELL_HEIGHT, display, border=1, fill=True)
            self.ln()
            fill = not fill


def export_workout_program_pdf(
    program_data: dict[str, Any],
    output_path: str | Path,
) -> Path:
    """Export a workout program as a formatted PDF.

    Args:
        program_data: Workout program dict with 'name', 'description',
                      and 'days' (list of day dicts with 'exercises').
        output_path: File path for the output PDF.

    Returns:
        Path to the generated PDF file.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    name = program_data.get("name", "Workout Program")
    pdf = PDFExporter(title=name)
    pdf.alias_nb_pages()
    pdf.add_page()

    # Description
    description = program_data.get("description", "")
    if description:
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 5, description)
        pdf.ln(5)

    # Days / exercises
    days = program_data.get("days", [])
    if not days:
        days = program_data.get("workout_days", [])

    for day in days:
        day_name = day.get("name", day.get("day", ""))
        exercises = day.get("exercises", [])

        if day_name:
            pdf.add_section_title(day_name)

        if not exercises:
            pdf.set_font("Helvetica", "I", 9)
            pdf.cell(0, _CELL_HEIGHT, "Rest day", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)
            continue

        headers = ["Exercise", "Sets", "Reps", "Rest", "Tempo"]
        rows = []
        for ex in exercises:
            rows.append(
                [
                    str(ex.get("name", ex.get("exercise_name", ""))),
                    str(ex.get("sets", "")),
                    str(ex.get("reps", "")),
                    str(ex.get("rest", "")),
                    str(ex.get("tempo", "")),
                ]
            )

        pdf.add_table(headers, rows)
        pdf.ln(5)

    pdf.output(str(path))
    logger.info("Exported workout program PDF: %s", path)
    return path


def export_checkin_summary_pdf(
    summary_data: dict[str, Any],
    output_path: str | Path,
    weight_unit: str = "kg",
    measurement_unit: str = "cm",
) -> Path:
    """Export a client's check-in summary as a formatted PDF.

    Args:
        summary_data: Dict with 'client_name', 'checkins' (list of check-in dicts),
                      and optional 'trends' dict.
        output_path: File path for the output PDF.
        weight_unit: Weight unit label (kg/lbs).
        measurement_unit: Measurement unit label (cm/inches).

    Returns:
        Path to the generated PDF file.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    client_name = summary_data.get("client_name", "Client")
    pdf = PDFExporter(title=f"Check-in Summary - {client_name}")
    pdf.alias_nb_pages()
    pdf.add_page(orientation="L")  # Landscape for wide tables

    checkins = summary_data.get("checkins", [])
    if not checkins:
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, _CELL_HEIGHT, "No check-in data available.", new_x="LMARGIN", new_y="NEXT")
        pdf.output(str(path))
        return path

    # Build table
    headers = [
        "Date",
        f"Weight ({weight_unit})",
        f"Waist ({measurement_unit})",
        f"Hips ({measurement_unit})",
        f"Biceps ({measurement_unit})",
        f"Thighs ({measurement_unit})",
        "Sleep",
        "Nutrition",
        "Stress",
        "Energy",
    ]

    rows = []
    for checkin in checkins:
        date = str(checkin.get("date", checkin.get("submitted_at", "")))[:10]
        rows.append(
            [
                date,
                _fmt_val(checkin.get("weight")),
                _fmt_val(checkin.get("waist")),
                _fmt_val(checkin.get("hips")),
                _fmt_val(checkin.get("biceps")),
                _fmt_val(checkin.get("thighs")),
                _fmt_val(checkin.get("sleep_quality")),
                _fmt_val(checkin.get("nutrition_adherence")),
                _fmt_val(checkin.get("stress_level")),
                _fmt_val(checkin.get("energy_level")),
            ]
        )

    col_widths = [25.0, 25.0, 25.0, 25.0, 25.0, 25.0, 20.0, 25.0, 20.0, 20.0]
    pdf.add_section_title("Check-in History")
    pdf.add_table(headers, rows, col_widths)

    # Trends section
    trends = summary_data.get("trends")
    if trends:
        pdf.ln(8)
        pdf.add_section_title("Trends")
        pdf.set_font("Helvetica", "", 10)
        for metric, trend_info in trends.items():
            if isinstance(trend_info, dict):
                direction = trend_info.get("direction", "")
                change = trend_info.get("change", "")
                pdf.cell(
                    0,
                    _CELL_HEIGHT,
                    f"{metric}: {direction} ({change})",
                    new_x="LMARGIN",
                    new_y="NEXT",
                )
            else:
                pdf.cell(
                    0,
                    _CELL_HEIGHT,
                    f"{metric}: {trend_info}",
                    new_x="LMARGIN",
                    new_y="NEXT",
                )

    pdf.output(str(path))
    logger.info("Exported check-in summary PDF: %s", path)
    return path


def export_workout_plan_pdf(
    plan_data: dict[str, Any],
    output_path: str | Path,
) -> Path:
    """Export a client's workout plan as a formatted PDF.

    Args:
        plan_data: Dict with 'client_name', 'plan_name', and 'days'
                   (list of day dicts with exercises).
        output_path: File path for the output PDF.

    Returns:
        Path to the generated PDF file.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    client_name = plan_data.get("client_name", "Client")
    plan_name = plan_data.get("plan_name", plan_data.get("name", "Workout Plan"))
    pdf = PDFExporter(title=f"{plan_name} - {client_name}")
    pdf.alias_nb_pages()
    pdf.add_page()

    # Notes / description
    notes = plan_data.get("notes", plan_data.get("description", ""))
    if notes:
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 5, str(notes))
        pdf.ln(5)

    days = plan_data.get("days", plan_data.get("workout_days", []))
    for day in days:
        day_name = day.get("name", day.get("day", ""))
        exercises = day.get("exercises", [])

        if day_name:
            pdf.add_section_title(day_name)

        if not exercises:
            pdf.set_font("Helvetica", "I", 9)
            pdf.cell(0, _CELL_HEIGHT, "Rest day", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)
            continue

        headers = ["Exercise", "Sets", "Reps", "Rest", "Tempo", "Notes"]
        rows = []
        for ex in exercises:
            rows.append(
                [
                    str(ex.get("name", ex.get("exercise_name", ""))),
                    str(ex.get("sets", "")),
                    str(ex.get("reps", "")),
                    str(ex.get("rest", "")),
                    str(ex.get("tempo", "")),
                    str(ex.get("notes", ""))[:30],
                ]
            )

        pdf.add_table(headers, rows)
        pdf.ln(5)

    pdf.output(str(path))
    logger.info("Exported workout plan PDF: %s", path)
    return path


def _fmt_val(value: Any) -> str:
    """Format a numeric value for table display."""
    if value is None:
        return "-"
    try:
        num = float(value)
        if num == int(num):
            return str(int(num))
        return f"{num:.1f}"
    except (ValueError, TypeError):
        return str(value)

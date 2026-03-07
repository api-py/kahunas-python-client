"""Chart generation for Kahunas progress data.

Generates PNG images for body weight, steps, body fat, and other metrics
over configurable time ranges (week, month, quarter, year, all).
"""

from __future__ import annotations

import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Supported metric types and their display configuration
METRIC_CONFIG: dict[str, dict[str, str]] = {
    "weight": {"label": "Body Weight", "unit": "kg", "color": "#2196F3"},
    "bodyfat": {"label": "Body Fat", "unit": "%", "color": "#FF9800"},
    "steps": {"label": "Steps", "unit": "steps", "color": "#4CAF50"},
    "chest": {"label": "Chest", "unit": "cm", "color": "#9C27B0"},
    "waist": {"label": "Waist", "unit": "cm", "color": "#F44336"},
    "hips": {"label": "Hips", "unit": "cm", "color": "#00BCD4"},
    "arms": {"label": "Arms", "unit": "cm", "color": "#FF5722"},
    "thighs": {"label": "Thighs", "unit": "cm", "color": "#607D8B"},
}

# Time range labels
RANGE_LABELS: dict[str, str] = {
    "week": "Last 7 Days",
    "month": "Last 30 Days",
    "quarter": "Last 90 Days",
    "year": "Last 365 Days",
    "all": "All Time",
}


def generate_chart(
    data_points: list[dict[str, Any]],
    metric: str = "weight",
    time_range: str = "all",
    title: str | None = None,
    client_name: str = "",
    output_path: str | None = None,
) -> bytes:
    """Generate a PNG chart image from progress data points.

    Args:
        data_points: List of dicts with 'date' and 'value' keys.
        metric: Metric type (weight, bodyfat, steps, etc.).
        time_range: Time range label (week, month, quarter, year, all).
        title: Custom chart title (auto-generated if None).
        client_name: Client name for the chart title.
        output_path: If provided, save PNG to this path.

    Returns:
        PNG image bytes.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    config = METRIC_CONFIG.get(metric, {"label": metric.title(), "unit": "", "color": "#2196F3"})

    # Parse data points
    dates: list[datetime] = []
    values: list[float] = []
    for point in data_points:
        date_str = point.get("date", point.get("label", ""))
        val = point.get("value", point.get("y", 0))
        if not date_str or val is None:
            continue
        try:
            dt = _parse_date(date_str)
            dates.append(dt)
            values.append(float(val))
        except (ValueError, TypeError):
            logger.debug("Skipping invalid data point: %s", point)

    if not dates:
        return _generate_empty_chart(config["label"], time_range, client_name)

    # Sort by date
    paired = sorted(zip(dates, values, strict=True), key=lambda x: x[0])
    dates, values = zip(*paired, strict=True)
    dates = list(dates)
    values = list(values)

    # Create the chart
    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor("#FAFAFA")
    ax.set_facecolor("#FAFAFA")

    # Plot line with markers
    ax.plot(
        dates,
        values,
        color=config["color"],
        linewidth=2,
        marker="o",
        markersize=4,
        markerfacecolor=config["color"],
        markeredgecolor="white",
        markeredgewidth=1,
        zorder=3,
    )

    # Fill area under the line
    ax.fill_between(dates, values, alpha=0.1, color=config["color"])

    # Add min/max/latest annotations
    if len(values) >= 2:
        latest = values[-1]
        first = values[0]
        change = latest - first
        pct = (change / first * 100) if first else 0
        sign = "+" if change >= 0 else ""
        ax.annotate(
            f"Latest: {latest:.1f} {config['unit']}\nChange: {sign}{change:.1f} ({sign}{pct:.1f}%)",
            xy=(dates[-1], latest),
            xytext=(15, 15),
            textcoords="offset points",
            fontsize=9,
            bbox={"boxstyle": "round,pad=0.4", "facecolor": "white", "edgecolor": "#DDD"},
            arrowprops={"arrowstyle": "->", "color": "#999"},
        )

    # Labels and title
    range_label = RANGE_LABELS.get(time_range, time_range.title())
    chart_title = title or f"{config['label']} — {range_label}"
    if client_name:
        chart_title = f"{client_name}: {chart_title}"
    ax.set_title(chart_title, fontsize=14, fontweight="bold", pad=12)
    ax.set_ylabel(f"{config['label']} ({config['unit']})", fontsize=11)
    ax.set_xlabel("Date", fontsize=11)

    # Format x-axis dates
    if len(dates) <= 14:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    elif len(dates) <= 60:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
    else:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
        ax.xaxis.set_major_locator(mdates.MonthLocator())

    fig.autofmt_xdate(rotation=30, ha="right")

    # Grid and styling
    ax.grid(True, alpha=0.3, linestyle="--")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Stats footer
    stats = (
        f"Min: {min(values):.1f}  |  Max: {max(values):.1f}  |  "
        f"Avg: {sum(values) / len(values):.1f}  |  "
        f"Points: {len(values)}"
    )
    fig.text(0.5, 0.01, stats, ha="center", fontsize=8, color="#888")

    fig.tight_layout(rect=(0, 0.03, 1, 1))

    # Export to PNG bytes
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    png_bytes = buf.read()

    # Optionally save to file
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png_bytes)
        logger.info("Chart saved to %s", path)

    return png_bytes


def _parse_date(date_str: str) -> datetime:
    """Parse various date formats from the Kahunas API."""
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%m/%d/%Y",
        "%b %d, %Y",
        "%B %d, %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {date_str}")


def _generate_empty_chart(label: str, time_range: str, client_name: str) -> bytes:
    """Generate a placeholder chart when there's no data."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor("#FAFAFA")
    ax.set_facecolor("#FAFAFA")

    range_label = RANGE_LABELS.get(time_range, time_range.title())
    title = f"{label} — {range_label}"
    if client_name:
        title = f"{client_name}: {title}"

    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.text(
        0.5,
        0.5,
        "No data available for this time range",
        ha="center",
        va="center",
        fontsize=14,
        color="#999",
        transform=ax.transAxes,
    )
    ax.set_xticks([])
    ax.set_yticks([])

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()

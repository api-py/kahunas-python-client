"""Tests for the persona / messaging template system."""

from __future__ import annotations

from pathlib import Path

from kahunas_client.persona import (
    DEFAULT_PERSONA_TEMPLATE,
    PersonaConfig,
    build_anomaly_warning,
    build_checkin_reminder,
    get_persona_summary,
    load_persona_template,
    render_message,
)

# ── DefaultPersonaTemplate ──


class TestDefaultPersonaTemplate:
    """Tests for the built-in default persona template."""

    def test_contains_london(self) -> None:
        assert "London" in DEFAULT_PERSONA_TEMPLATE

    def test_contains_british_english(self) -> None:
        assert "British English" in DEFAULT_PERSONA_TEMPLATE

    def test_contains_experience(self) -> None:
        assert "15 years" in DEFAULT_PERSONA_TEMPLATE

    def test_contains_weight_placeholder(self) -> None:
        assert "${weight_deviation_pct}" in DEFAULT_PERSONA_TEMPLATE

    def test_contains_sleep_placeholder(self) -> None:
        assert "${sleep_minimum}" in DEFAULT_PERSONA_TEMPLATE

    def test_contains_step_placeholder(self) -> None:
        assert "${step_minimum}" in DEFAULT_PERSONA_TEMPLATE

    def test_contains_client_name_placeholder(self) -> None:
        assert "${client_name}" in DEFAULT_PERSONA_TEMPLATE

    def test_contains_context_placeholder(self) -> None:
        assert "${context}" in DEFAULT_PERSONA_TEMPLATE

    def test_is_non_empty(self) -> None:
        assert len(DEFAULT_PERSONA_TEMPLATE) > 100


# ── PersonaConfig ──


class TestPersonaConfig:
    """Tests for PersonaConfig dataclass."""

    def test_default_values(self) -> None:
        pc = PersonaConfig()
        assert pc.template == DEFAULT_PERSONA_TEMPLATE
        assert pc.weight_deviation_pct == 20.0
        assert pc.sleep_minimum == 7.0
        assert pc.step_minimum == 5000

    def test_custom_template(self) -> None:
        pc = PersonaConfig(template="Custom template")
        assert pc.template == "Custom template"

    def test_empty_template_uses_default(self) -> None:
        pc = PersonaConfig(template="")
        assert pc.template == DEFAULT_PERSONA_TEMPLATE

    def test_custom_thresholds(self) -> None:
        pc = PersonaConfig(weight_deviation_pct=10.0, sleep_minimum=6.0, step_minimum=8000)
        assert pc.weight_deviation_pct == 10.0
        assert pc.sleep_minimum == 6.0
        assert pc.step_minimum == 8000

    def test_from_config_with_inline(self) -> None:
        pc = PersonaConfig.from_config(persona_template="Inline template")
        assert pc.template == "Inline template"

    def test_from_config_with_file(self, tmp_path: Path) -> None:
        tpl_file = tmp_path / "persona.txt"
        tpl_file.write_text("File template content")
        pc = PersonaConfig.from_config(persona_template_path=str(tpl_file))
        assert pc.template == "File template content"

    def test_from_config_file_priority_over_inline(self, tmp_path: Path) -> None:
        tpl_file = tmp_path / "persona.txt"
        tpl_file.write_text("From file")
        pc = PersonaConfig.from_config(
            persona_template="From inline",
            persona_template_path=str(tpl_file),
        )
        assert pc.template == "From file"

    def test_from_config_default(self) -> None:
        pc = PersonaConfig.from_config()
        assert pc.template == DEFAULT_PERSONA_TEMPLATE


# ── load_persona_template ──


class TestLoadPersonaTemplate:
    """Tests for template loading with priority order."""

    def test_default_when_no_args(self) -> None:
        result = load_persona_template()
        assert result == DEFAULT_PERSONA_TEMPLATE

    def test_inline_template(self) -> None:
        result = load_persona_template(template="My custom style")
        assert result == "My custom style"

    def test_inline_stripped(self) -> None:
        result = load_persona_template(template="  with spaces  ")
        assert result == "with spaces"

    def test_file_template(self, tmp_path: Path) -> None:
        tpl = tmp_path / "tpl.txt"
        tpl.write_text("  File content  ")
        result = load_persona_template(template_path=str(tpl))
        assert result == "File content"

    def test_file_priority_over_inline(self, tmp_path: Path) -> None:
        tpl = tmp_path / "tpl.txt"
        tpl.write_text("File wins")
        result = load_persona_template(template="Inline", template_path=str(tpl))
        assert result == "File wins"

    def test_missing_file_falls_to_inline(self) -> None:
        result = load_persona_template(
            template="Fallback inline",
            template_path="/nonexistent/path/persona.txt",
        )
        assert result == "Fallback inline"

    def test_missing_file_no_inline_uses_default(self) -> None:
        result = load_persona_template(template_path="/nonexistent/path/persona.txt")
        assert result == DEFAULT_PERSONA_TEMPLATE

    def test_empty_strings_use_default(self) -> None:
        result = load_persona_template(template="", template_path="")
        assert result == DEFAULT_PERSONA_TEMPLATE


# ── render_message ──


class TestRenderMessage:
    """Tests for template rendering."""

    def test_basic_substitution(self) -> None:
        result = render_message("Hello ${name}", name="Alice")
        assert result == "Hello Alice"

    def test_multiple_variables(self) -> None:
        result = render_message("${a} and ${b}", a="X", b="Y")
        assert result == "X and Y"

    def test_missing_variable_left_as_is(self) -> None:
        result = render_message("Hello ${name}", age="25")
        assert "${name}" in result

    def test_empty_template(self) -> None:
        result = render_message("")
        assert result == ""

    def test_no_variables(self) -> None:
        result = render_message("Plain text")
        assert result == "Plain text"

    def test_numeric_value(self) -> None:
        result = render_message("Count: ${count}", count=42)
        assert result == "Count: 42"

    def test_special_characters_in_value(self) -> None:
        result = render_message("Hi ${name}", name="O'Brien & Co.")
        assert "O'Brien & Co." in result


# ── build_checkin_reminder ──


class TestBuildCheckinReminder:
    """Tests for check-in reminder message generation."""

    def test_contains_client_name(self) -> None:
        msg = build_checkin_reminder("Alice", 7)
        assert "Alice" in msg

    def test_contains_days_overdue(self) -> None:
        msg = build_checkin_reminder("Bob", 14)
        assert "14" in msg

    def test_contains_check_in_prompt(self) -> None:
        msg = build_checkin_reminder("Charlie", 5)
        assert "check-in" in msg.lower()

    def test_greeting(self) -> None:
        msg = build_checkin_reminder("Diana", 3)
        assert "Hello Diana" in msg

    def test_sign_off(self) -> None:
        msg = build_checkin_reminder("Eve", 7)
        assert "Your Coach" in msg

    def test_extra_context_included(self) -> None:
        msg = build_checkin_reminder("Frank", 10, extra_context="New program starts Monday")
        assert "New program starts Monday" in msg

    def test_no_extra_context(self) -> None:
        msg = build_checkin_reminder("Grace", 7, extra_context="")
        assert msg.strip().endswith("Your Coach")


# ── build_anomaly_warning ──


class TestBuildAnomalyWarning:
    """Tests for anomaly warning message generation."""

    def test_empty_anomalies_returns_empty(self) -> None:
        result = build_anomaly_warning("Alice", [])
        assert result == ""

    def test_contains_client_name(self) -> None:
        anomalies = [{"metric": "Weight", "message": "Dropped 5kg"}]
        msg = build_anomaly_warning("Bob", anomalies)
        assert "Bob" in msg

    def test_contains_anomaly_details(self) -> None:
        anomalies = [{"metric": "Weight", "message": "Gained 10%"}]
        msg = build_anomaly_warning("Charlie", anomalies)
        assert "Weight" in msg
        assert "Gained 10%" in msg

    def test_multiple_anomalies_numbered(self) -> None:
        anomalies = [
            {"metric": "Weight", "message": "Up 15%"},
            {"metric": "Sleep", "message": "Dropped to 4"},
        ]
        msg = build_anomaly_warning("Diana", anomalies)
        assert "1." in msg
        assert "2." in msg

    def test_sign_off(self) -> None:
        anomalies = [{"metric": "Stress", "message": "Increased significantly"}]
        msg = build_anomaly_warning("Eve", anomalies)
        assert "Your Coach" in msg

    def test_extra_context(self) -> None:
        anomalies = [{"metric": "Weight", "message": "Changed"}]
        msg = build_anomaly_warning("Frank", anomalies, extra_context="Please call me")
        assert "Please call me" in msg


# ── get_persona_summary ──


class TestGetPersonaSummary:
    """Tests for persona summary output."""

    def test_default_template_source(self) -> None:
        pc = PersonaConfig()
        summary = get_persona_summary(pc)
        assert summary["template_source"] == "default"

    def test_custom_template_source(self) -> None:
        pc = PersonaConfig(template="Custom")
        summary = get_persona_summary(pc)
        assert summary["template_source"] == "custom"

    def test_includes_thresholds(self) -> None:
        pc = PersonaConfig(weight_deviation_pct=25.0, sleep_minimum=6.5, step_minimum=8000)
        summary = get_persona_summary(pc)
        assert summary["weight_deviation_pct"] == 25.0
        assert summary["sleep_minimum"] == 6.5
        assert summary["step_minimum"] == 8000

    def test_template_preview_truncated(self) -> None:
        pc = PersonaConfig()
        summary = get_persona_summary(pc)
        assert len(summary["template_preview"]) <= 203  # 200 + "..."

    def test_short_template_not_truncated(self) -> None:
        pc = PersonaConfig(template="Short")
        summary = get_persona_summary(pc)
        assert summary["template_preview"] == "Short"
        assert "..." not in summary["template_preview"]

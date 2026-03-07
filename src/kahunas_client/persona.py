"""Messaging persona and template system for Kahunas coaching communications.

Provides a configurable persona template that controls the tone, style, and
content of messages sent to coaching clients. The default persona is a
London-based personal trainer with 15 years of experience, using polite
British English.

Template priority (highest first):
    1. File path (KAHUNAS_PERSONA_TEMPLATE_PATH)
    2. Inline template (KAHUNAS_PERSONA_TEMPLATE)
    3. Built-in default
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_PERSONA_TEMPLATE = """\
You are a personal trainer based in London, UK, with 15 years of professional \
experience. You hold certifications in Level 3 Personal Training, Precision \
Nutrition L1, and NASM Corrective Exercise. You communicate in polite, \
respectful British English.

When messaging clients:
- Be encouraging but honest about their progress.
- Highlight weight deviations greater than ${weight_deviation_pct}% within a week.
- Flag sleep deprivation when average sleep quality drops below ${sleep_minimum} hours.
- Flag low activity when daily step count drops below ${step_minimum} steps.
- Use a warm, professional tone. Avoid slang or overly casual language.
- Address the client by their first name.

Client: ${client_name}
Context: ${context}
"""

_REMINDER_TEMPLATE = """\
Hello ${client_name},

I hope you're doing well. I noticed it has been ${days_overdue} days since \
your last check-in. Regular check-ins are really important for tracking your \
progress and keeping us both on the same page.

When you get a moment, please submit your latest check-in so we can review \
how things are going and adjust your programme if needed.

${extra_context}\
Looking forward to hearing from you.

Best regards,
Your Coach\
"""

_ANOMALY_TEMPLATE = """\
Hello ${client_name},

I've been reviewing your recent check-in data and noticed a few things I'd \
like to bring to your attention:

${anomaly_details}

These changes are worth discussing so we can understand what's happening and \
make any necessary adjustments to your programme.

${extra_context}\
Please don't hesitate to reach out if you'd like to chat about this.

Best regards,
Your Coach\
"""


@dataclass
class PersonaConfig:
    """Configuration for the messaging persona.

    Attributes:
        template: The persona template text.
        weight_deviation_pct: Weight deviation % to highlight.
        sleep_minimum: Sleep hours below which to flag concern.
        step_minimum: Step count below which to flag concern.
    """

    template: str = ""
    weight_deviation_pct: float = 20.0
    sleep_minimum: float = 7.0
    step_minimum: int = 5000

    def __post_init__(self) -> None:
        if not self.template:
            self.template = DEFAULT_PERSONA_TEMPLATE

    @classmethod
    def from_config(
        cls,
        persona_template: str = "",
        persona_template_path: str = "",
        weight_deviation_pct: float = 20.0,
        sleep_minimum: float = 7.0,
        step_minimum: int = 5000,
    ) -> PersonaConfig:
        """Build from config fields, respecting priority order."""
        template = load_persona_template(persona_template, persona_template_path)
        return cls(
            template=template,
            weight_deviation_pct=weight_deviation_pct,
            sleep_minimum=sleep_minimum,
            step_minimum=step_minimum,
        )


def load_persona_template(
    template: str = "",
    template_path: str = "",
) -> str:
    """Load persona template with priority: file > inline > default.

    Args:
        template: Inline template text.
        template_path: Path to a template file.

    Returns:
        The resolved template string.
    """
    # Priority 1: File path
    if template_path:
        path = Path(template_path)
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8").strip()
            except OSError:
                logger.warning("Could not read persona template file: %s", template_path)
        else:
            logger.warning("Persona template file not found: %s", template_path)

    # Priority 2: Inline template
    if template:
        return template.strip()

    # Priority 3: Default
    return DEFAULT_PERSONA_TEMPLATE


def render_message(
    template: str,
    **kwargs: Any,
) -> str:
    """Render a template with safe substitution of variables.

    Uses Python's string.Template for safe substitution — missing
    variables are left as-is rather than raising errors.

    Args:
        template: Template string with ${variable} placeholders.
        **kwargs: Variable values to substitute.

    Returns:
        Rendered message string.
    """
    return Template(template).safe_substitute(**kwargs)


def build_checkin_reminder(
    client_name: str,
    days_overdue: int,
    persona: PersonaConfig | None = None,
    extra_context: str = "",
) -> str:
    """Build a check-in reminder message for an overdue client.

    Args:
        client_name: The client's first name.
        days_overdue: Number of days since their last check-in.
        persona: Optional persona config (for future persona-aware reminders).
        extra_context: Additional context to include in the message.

    Returns:
        Formatted reminder message.
    """
    return render_message(
        _REMINDER_TEMPLATE,
        client_name=client_name,
        days_overdue=str(days_overdue),
        extra_context=f"{extra_context}\n\n" if extra_context else "",
    )


def build_anomaly_warning(
    client_name: str,
    anomalies: list[dict[str, Any]],
    persona: PersonaConfig | None = None,
    extra_context: str = "",
) -> str:
    """Build an anomaly warning message for a client.

    Args:
        client_name: The client's first name.
        anomalies: List of anomaly dicts with 'metric', 'message' keys.
        persona: Optional persona config.
        extra_context: Additional context to include.

    Returns:
        Formatted warning message.
    """
    if not anomalies:
        return ""

    details_lines = []
    for i, anomaly in enumerate(anomalies, 1):
        metric = anomaly.get("metric", "Unknown")
        message = anomaly.get("message", "Value changed significantly")
        details_lines.append(f"{i}. {metric}: {message}")

    anomaly_details = "\n".join(details_lines)

    return render_message(
        _ANOMALY_TEMPLATE,
        client_name=client_name,
        anomaly_details=anomaly_details,
        extra_context=f"{extra_context}\n\n" if extra_context else "",
    )


def get_persona_summary(persona: PersonaConfig) -> dict[str, Any]:
    """Return a summary of the persona config for MCP tool output.

    Args:
        persona: The persona config to summarise.

    Returns:
        Dict with persona details.
    """
    is_default = persona.template == DEFAULT_PERSONA_TEMPLATE
    return {
        "template_source": "default" if is_default else "custom",
        "weight_deviation_pct": persona.weight_deviation_pct,
        "sleep_minimum": persona.sleep_minimum,
        "step_minimum": persona.step_minimum,
        "template_preview": persona.template[:200] + ("..." if len(persona.template) > 200 else ""),
    }

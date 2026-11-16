"""
guardrails/__init__.py
======================
Shared types used by all guardrail modules.

GuardrailResult  — the standard return type of every check function.
GuardrailSeverity — severity classification of a guardrail event.
"""

from dataclasses import dataclass, field
from enum import Enum


class GuardrailSeverity(str, Enum):
    """
    Severity level of a guardrail event.

    INFO    — informational only; no action required.
    WARNING — flag for review; pipeline continues.
    BLOCK   — pipeline must stop; returned as passed=False.
    """
    INFO    = "INFO"
    WARNING = "WARNING"
    BLOCK   = "BLOCK"


@dataclass
class GuardrailResult:
    """
    Returned by every guardrail check function.

    Attributes:
        passed:   True  → content is safe to proceed.
                  False → pipeline must abort this step.
        reason:   Human-readable explanation of the result.
        layer:    Which guardrail module produced this result.
        severity: INFO | WARNING | BLOCK (auto-derived from passed when not set).
        details:  Optional structured metadata about the detection
                  (e.g. {"pii_types": ["email"], "pattern": "..."}).
    """
    passed:   bool
    reason:   str
    layer:    str                    = ""
    severity: GuardrailSeverity      = GuardrailSeverity.INFO
    details:  dict                   = field(default_factory=dict)

    def __post_init__(self):
        # Auto-derive severity when caller only sets passed
        if not self.passed and self.severity == GuardrailSeverity.INFO:
            self.severity = GuardrailSeverity.BLOCK

    def to_dict(self) -> dict:
        return {
            "passed":   self.passed,
            "reason":   self.reason,
            "layer":    self.layer,
            "severity": self.severity.value,
            "details":  self.details,
        }

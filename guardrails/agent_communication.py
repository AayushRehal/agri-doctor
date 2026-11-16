"""
guardrails/agent_communication.py
===================================
Inter-agent communication validation guardrails.

Validates the message payload passed from the Pathologist Agent to the
Extension Officer Agent, ensuring the downstream agent always receives
a structurally valid, non-corrupted input.

Checks implemented:
  1. Schema validation — required keys exist in the diagnosis dict
  2. Type validation   — values are strings (not None, list, etc.)
  3. Upstream error propagation guard — block if Pathologist errored
  4. Confidence coherence — confidence % consistent with severity label
  5. Payload integrity   — no unexpected keys that could carry injected content

Public API:
  check_diagnosis_message(diagnosis: dict) -> GuardrailResult
"""

import re
from guardrails import GuardrailResult, GuardrailSeverity

# ── Schema definition ─────────────────────────────────────────────────────────
# Keys the Pathologist must produce; Extension Officer requires all of these.
_REQUIRED_KEYS  = {"disease_name", "confidence", "severity", "symptoms_observed"}

# Keys that are allowed in the message; anything else is stripped before passing
_ALLOWED_KEYS   = {
    "disease_name", "confidence", "severity", "symptoms_observed",
    "raw_response", "tokens_used", "latency_ms", "error", "guardrail_result",
}

VALID_SEVERITIES = {"mild", "moderate", "severe", "none"}

# Confidence % pattern
_CONFIDENCE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")

# Severity → expected confidence range mapping
# Used to detect logical contradictions (e.g. Severe + 5% confidence)
_SEVERITY_CONF_RANGES = {
    "none":     (0,   30),
    "mild":     (10,  70),
    "moderate": (40, 100),
    "severe":   (55, 100),
}


# ── Public API ────────────────────────────────────────────────────────────────

def check_diagnosis_message(diagnosis: dict) -> GuardrailResult:
    """
    Validate the diagnosis dict produced by PathologistAgent before it is
    passed to ExtensionOfficerAgent.

    Args:
        diagnosis: Return value of PathologistAgent.analyse().

    Returns:
        GuardrailResult with layer="agent_communication"
        passed=False if the message is invalid and should not be forwarded.
    """
    layer = "agent_communication"

    if not isinstance(diagnosis, dict):
        return GuardrailResult(
            passed=False,
            reason=f"Diagnosis message is not a dict (got {type(diagnosis).__name__}). "
                   "Agent communication aborted.",
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
        )

    # 1. Upstream error guard — Pathologist already flagged an error
    if diagnosis.get("error"):
        return GuardrailResult(
            passed=False,
            reason=f"Pathologist Agent reported an error: {diagnosis['error']}. "
                   "Extension Officer Agent will not be called.",
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
            details={"upstream_error": str(diagnosis["error"])},
        )

    # 2. Required key presence
    missing = _REQUIRED_KEYS - set(diagnosis.keys())
    if missing:
        return GuardrailResult(
            passed=False,
            reason=f"Diagnosis message is missing required fields: {', '.join(sorted(missing))}.",
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
            details={"missing_keys": sorted(missing)},
        )

    # 3. Type validation — all required fields must be non-empty strings
    type_errors = []
    for key in _REQUIRED_KEYS:
        val = diagnosis.get(key)
        if not isinstance(val, str) or not val.strip():
            type_errors.append(key)

    if type_errors:
        return GuardrailResult(
            passed=False,
            reason=f"Diagnosis fields have invalid or empty values: {', '.join(type_errors)}.",
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
            details={"invalid_fields": type_errors},
        )

    # 4. Severity value validation
    sev_raw = diagnosis.get("severity", "").strip().lower()
    if sev_raw and sev_raw not in VALID_SEVERITIES:
        return GuardrailResult(
            passed=False,
            reason=f"Diagnosis severity '{diagnosis['severity']}' is not a valid value. "
                   f"Expected: Mild, Moderate, Severe, or None.",
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
            details={"severity": diagnosis["severity"]},
        )

    # 5. Confidence coherence check (soft — WARNING, not BLOCK)
    conf_str = diagnosis.get("confidence", "")
    conf_match = _CONFIDENCE_RE.search(conf_str)
    if conf_match and sev_raw in _SEVERITY_CONF_RANGES:
        conf_val = float(conf_match.group(1))
        low, high = _SEVERITY_CONF_RANGES[sev_raw]
        if not (low <= conf_val <= high):
            return GuardrailResult(
                passed=True,
                reason=(
                    f"Confidence {conf_val}% may be inconsistent with severity '{diagnosis['severity']}' "
                    f"(expected {low}–{high}%). Results should be verified."
                ),
                layer=layer,
                severity=GuardrailSeverity.WARNING,
                details={"confidence": conf_val, "severity": sev_raw, "expected_range": [low, high]},
            )

    # 6. Unexpected-key injection guard
    unexpected = set(diagnosis.keys()) - _ALLOWED_KEYS
    if unexpected:
        return GuardrailResult(
            passed=True,
            reason=f"Diagnosis message contains unexpected keys that will be ignored: {unexpected}.",
            layer=layer,
            severity=GuardrailSeverity.WARNING,
            details={"unexpected_keys": sorted(unexpected)},
        )

    return GuardrailResult(
        passed=True,
        reason="Diagnosis message passed all inter-agent communication checks.",
        layer=layer,
        severity=GuardrailSeverity.INFO,
    )

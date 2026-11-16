"""
guardrails/output_guardrails.py
================================
Validates LLM responses before they are presented to the user.

Checks implemented:
  1.  Minimum response length
  2.  Model refusal / inability detection
  3.  Hallucination risk scoring (vague / fabricated content signals)
  4.  Structural completeness — expected fields must be present
  5.  Confidence range sanity (Pathologist output: 0–100%)
  6.  Severity field validation (Pathologist output)
  7.  Uncertainty flag (WARNING, not BLOCK)

Public API:
  check_response(text)                        -> GuardrailResult  (generic)
  check_diagnosis_output(text, parsed)        -> GuardrailResult  (Pathologist)
  check_recommendation_output(text, parsed)   -> GuardrailResult  (Extension Officer)
"""

import re
from guardrails import GuardrailResult, GuardrailSeverity

# ── Constants ─────────────────────────────────────────────────────────────────
MIN_RESPONSE_CHARS           = 50
HALLUCINATION_SCORE_THRESHOLD = 3     # block if hallucination score ≥ this value

# Required fields for each agent's structured output
_DIAGNOSIS_REQUIRED_FIELDS = ["disease_name", "confidence", "severity", "symptoms_observed"]
_RECOMMENDATION_REQUIRED_FIELDS = ["treatment", "prevention", "safe_chemicals", "farmer_advisory"]

VALID_SEVERITIES = {"mild", "moderate", "severe", "none"}

# ── Refusal patterns ──────────────────────────────────────────────────────────
_REFUSAL_PATTERNS = [
    r"i\s+(cannot|can't|am\s+unable\s+to|won't|will\s+not)\s+(help|assist|answer|provide|analyze|analyse)",
    r"as\s+an\s+ai\s+(language\s+model|assistant),?\s+i",
    r"i\s+don'?t\s+have\s+(the\s+ability|access|information)",
    r"i\s+am\s+not\s+able\s+to\s+(view|see|analyse|analyze|process)\s+(the\s+)?(image|photo|picture)",
    r"no\s+image\s+(was\s+)?(provided|found|attached|uploaded)",
    r"i\s+cannot\s+see\s+(any\s+)?(image|photo|picture|crop)",
    r"i\s+do\s+not\s+have\s+(the\s+)?(capability|ability)\s+to\s+(process|view|analyse|analyze)",
]
_REFUSAL_RE = re.compile("|".join(_REFUSAL_PATTERNS), flags=re.IGNORECASE | re.DOTALL)

# ── Hallucination risk signals ────────────────────────────────────────────────
# Each matched pattern adds 1 point to the hallucination score.
# Score ≥ HALLUCINATION_SCORE_THRESHOLD → block.
_HALLUCINATION_SIGNALS = [
    # Fabricated specificity with no basis
    (r"\bI\s+believe\s+this\s+is\b", 1),
    (r"\bthis\s+(looks?|appears?|seems?)\s+like\s+it\s+could\s+be\b", 1),
    (r"\bprobably\s+caused\s+by\b", 1),
    (r"\bmight\s+be\s+suffering\s+from\b", 1),
    # Contradictory confidence phrasing
    (r"\b100%\s+certain\b", 1),
    (r"\bguaranteed\s+to\s+(work|cure|fix)\b", 1),
    # Refusing to commit while still naming a disease
    (r"\bhard\s+to\s+(say|tell|determine)\s+without\s+testing\b", 1),
    (r"\bcould\s+be\s+(one\s+of\s+(many|several)|any\s+number)\b", 1),
    # Fabricated product names or unverifiable statistics
    (r"\b(studies\s+show|research\s+proves)\s+that\b", 1),
    (r"\b\d+%\s+of\s+farmers\s+(report|say|confirm)\b", 1),
]

# ── Uncertainty markers ───────────────────────────────────────────────────────
# These are WARNING-level only — do not block but flag for review.
_UNCERTAINTY_PATTERNS = [
    r"i\s+(am\s+not\s+sure|'?m\s+not\s+certain|cannot\s+be\s+certain)",
    r"it\s+(is\s+)?difficult\s+to\s+(determine|tell|say)",
    r"without\s+(more\s+)?information",
    r"consult\s+a\s+(professional|specialist|expert|doctor|agronomist|extension officer)",
    r"further\s+(laboratory|lab|field)\s+(testing|analysis|examination)\s+(is\s+)?(recommended|required|needed)",
]
_UNCERTAINTY_RE = re.compile("|".join(_UNCERTAINTY_PATTERNS), flags=re.IGNORECASE)

# ── Confidence percentage pattern ─────────────────────────────────────────────
_CONFIDENCE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


# ── Public API ────────────────────────────────────────────────────────────────

def check_response(text: str) -> GuardrailResult:
    """
    Generic LLM response validation.

    Checks: minimum length, refusal markers, hallucination score, uncertainty flags.

    Returns:
        GuardrailResult with layer="output_response"
    """
    layer = "output_response"

    # 1. Minimum length
    if not text or len(text.strip()) < MIN_RESPONSE_CHARS:
        return GuardrailResult(
            passed=False,
            reason=f"Response is too short ({len((text or '').strip())} chars). "
                   "The model may have failed to generate a useful answer.",
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
            details={"char_count": len((text or "").strip())},
        )

    # 2. Refusal detection
    if _REFUSAL_RE.search(text):
        return GuardrailResult(
            passed=False,
            reason="Model response indicates it could not process the input. "
                   "This may be an image encoding issue or model limitation.",
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
        )

    # 3. Hallucination scoring
    score = 0
    triggered = []
    for pattern, weight in _HALLUCINATION_SIGNALS:
        if re.search(pattern, text, re.IGNORECASE):
            score += weight
            triggered.append(pattern[:40])

    if score >= HALLUCINATION_SCORE_THRESHOLD:
        return GuardrailResult(
            passed=False,
            reason=f"Response scored {score}/{HALLUCINATION_SCORE_THRESHOLD} on the hallucination risk scale. "
                   "The response contains multiple vague or unverifiable claims.",
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
            details={"hallucination_score": score, "signals": triggered},
        )

    # 4. Uncertainty flag (WARNING — do not block)
    if _UNCERTAINTY_RE.search(text):
        return GuardrailResult(
            passed=True,
            reason="Response contains uncertainty markers — results should be validated "
                   "by a qualified agronomist before action is taken.",
            layer=layer,
            severity=GuardrailSeverity.WARNING,
        )

    return GuardrailResult(
        passed=True,
        reason="Response passed all checks.",
        layer=layer,
        severity=GuardrailSeverity.INFO,
    )


def check_diagnosis_output(raw_text: str, parsed: dict) -> GuardrailResult:
    """
    Validate parsed Pathologist Agent output for structural completeness
    and value sanity.

    Checks:
      - All required fields populated (not "Unknown" or empty)
      - Confidence value is a numeric percentage in 0–100 range
      - Severity is one of the recognised values

    Args:
        raw_text: Original text from the model (for generic checks).
        parsed:   Dict from pathologist._parse_diagnosis().

    Returns:
        GuardrailResult with layer="output_diagnosis"
    """
    layer = "output_diagnosis"

    # Run the generic checks first
    generic = check_response(raw_text)
    if not generic.passed:
        return GuardrailResult(
            passed=False,
            reason=generic.reason,
            layer=layer,
            severity=generic.severity,
            details=generic.details,
        )

    # 1. Required fields completeness
    missing = [
        f for f in _DIAGNOSIS_REQUIRED_FIELDS
        if not parsed.get(f) or parsed[f].strip().lower() in ("unknown", "")
    ]
    if missing:
        return GuardrailResult(
            passed=False,
            reason=f"Diagnosis response is missing required fields: {', '.join(missing)}.",
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
            details={"missing_fields": missing},
        )

    # 2. Confidence sanity (must be a number 0–100)
    conf_str = parsed.get("confidence", "")
    conf_match = _CONFIDENCE_RE.search(conf_str)
    if conf_match:
        conf_val = float(conf_match.group(1))
        if not (0.0 <= conf_val <= 100.0):
            return GuardrailResult(
                passed=False,
                reason=f"Confidence value {conf_val}% is outside the valid 0–100% range.",
                layer=layer,
                severity=GuardrailSeverity.BLOCK,
                details={"confidence": conf_str},
            )

    # 3. Severity validation
    sev = parsed.get("severity", "").strip().lower()
    if sev and sev not in VALID_SEVERITIES:
        return GuardrailResult(
            passed=False,
            reason=f"Severity '{parsed['severity']}' is not a recognised value "
                   f"(expected: Mild, Moderate, Severe, or None).",
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
            details={"severity": parsed["severity"]},
        )

    # Carry forward uncertainty warning if present
    if generic.severity == GuardrailSeverity.WARNING:
        return GuardrailResult(
            passed=True,
            reason=generic.reason,
            layer=layer,
            severity=GuardrailSeverity.WARNING,
        )

    return GuardrailResult(
        passed=True,
        reason="Diagnosis output passed all structural checks.",
        layer=layer,
        severity=GuardrailSeverity.INFO,
    )


def check_recommendation_output(raw_text: str, parsed: dict) -> GuardrailResult:
    """
    Validate parsed Extension Officer Agent output for structural completeness.

    Checks:
      - All four recommendation fields are populated and non-trivial
      - No field contains the placeholder "Not available."

    Args:
        raw_text: Original text from the model.
        parsed:   Dict from extension_officer._parse_recommendations().

    Returns:
        GuardrailResult with layer="output_recommendation"
    """
    layer = "output_recommendation"

    # Run the generic checks first
    generic = check_response(raw_text)
    if not generic.passed:
        return GuardrailResult(
            passed=False,
            reason=generic.reason,
            layer=layer,
            severity=generic.severity,
            details=generic.details,
        )

    # Required fields completeness
    missing = [
        f for f in _RECOMMENDATION_REQUIRED_FIELDS
        if not parsed.get(f) or parsed[f].strip().lower() in ("not available.", "")
    ]
    if missing:
        return GuardrailResult(
            passed=False,
            reason=f"Recommendation response is missing required fields: {', '.join(missing)}.",
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
            details={"missing_fields": missing},
        )

    # Carry forward uncertainty warning if present
    if generic.severity == GuardrailSeverity.WARNING:
        return GuardrailResult(
            passed=True,
            reason=generic.reason,
            layer=layer,
            severity=GuardrailSeverity.WARNING,
        )

    return GuardrailResult(
        passed=True,
        reason="Recommendation output passed all structural checks.",
        layer=layer,
        severity=GuardrailSeverity.INFO,
    )

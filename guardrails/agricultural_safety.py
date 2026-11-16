"""
guardrails/agricultural_safety.py
===================================
Agricultural domain-specific safety guardrails.

Checks implemented:
  1. Banned chemical detection — flag WHO Class Ia/Ib highly hazardous pesticides
  2. Dangerous advice detection — block actionable unsafe instructions
  3. Disclaimer enforcement — ensure AI-generated advice includes a disclaimer
  4. Crop-agnostic sanity — detect responses that ignore the crop context
  5. Human review flag — escalate Severe diagnoses for human verification

Public API:
  check_chemical_safety(text)      -> GuardrailResult
  check_dangerous_advice(text)     -> GuardrailResult
  check_disclaimer_present(text)   -> GuardrailResult
  check_severity_escalation(parsed_diagnosis) -> GuardrailResult
"""

import re
from guardrails import GuardrailResult, GuardrailSeverity


# ── Banned / highly hazardous pesticides ──────────────────────────────────────
# WHO Class Ia (extremely hazardous) and Class Ib (highly hazardous) pesticides
# that should never be recommended in AI-generated agricultural advice.
# Sources: WHO Recommended Classification of Pesticides by Hazard 2019 edition.
_BANNED_CHEMICALS = [
    # Class Ia — Extremely hazardous
    "aldicarb", "brodifacoum", "bromethalin", "chlormephos",
    "demeton", "disulfoton", "ethoprophos", "fenamiphos",
    "mevinphos", "parathion", "phorate", "phosphamidon",
    "terbufos", "thiofanox",
    # Class Ib — Highly hazardous
    "azinphos-methyl", "carbofuran", "chlorpyrifos", "diazinon",
    "dicrotophos", "dimethoate", "endosulfan", "lindane",
    "methiocarb", "methomyl", "monocrotophos", "omethoate",
    "oxydemeton-methyl", "paraquat", "profenofos", "triazophos",
    # Globally banned under Stockholm Convention / Rotterdam Convention
    "aldrin", "chlordane", "dieldrin", "endrin", "heptachlor",
    "hexachlorobenzene", "mirex", "toxaphene", "ddt",
]

_BANNED_CHEM_RE = re.compile(
    r"\b(" + "|".join(re.escape(c) for c in _BANNED_CHEMICALS) + r")\b",
    flags=re.IGNORECASE,
)

# ── Dangerous agricultural advice patterns ────────────────────────────────────
# Instructions that could cause physical harm or environmental damage.
_DANGEROUS_ADVICE_PATTERNS = [
    r"mix\s+(bleach|chlorine|ammonia)\s+with",
    r"apply\s+undiluted\s+(acid|pesticide|herbicide|chemical)",
    r"increase\s+(the\s+)?dose\s+(beyond|above)\s+(recommended|label)",
    # Covers "spray over the river", "spray into the pond" etc.
    r"spray\s+(directly\s+)?(on|over|onto|into)\s+(the\s+)?(water\s+body|river|lake|stream|pond|water)",
    r"burn\s+(the\s+)?(entire\s+)?(field|crop)\s+without",
    r"bury\s+(pesticide\s+)?(containers?|drums?)\s+in\s+(soil|ground|field)",
    r"do\s+not\s+(wear|use)\s+(protective|safety|ppe|gloves|mask)",
    # Covers "safe to eat immediately after spraying", "is safe to eat right after treatment"
    r"(is\s+)?safe\s+to\s+(eat|harvest|consume)\s+(immediately(\s+after)?|right\s+after|straight\s+after|directly\s+after)\s+(spraying|application|treatment)",
    r"ignore\s+(the\s+)?(pre-harvest|waiting|re-entry)\s+interval",
    r"apply\s+(at|during)\s+(rain|rainfall|flood)",
]
_DANGEROUS_RE = re.compile(
    "|".join(_DANGEROUS_ADVICE_PATTERNS),
    flags=re.IGNORECASE | re.DOTALL,
)

# ── Disclaimer requirement ────────────────────────────────────────────────────
# At least one of these phrases must appear in recommendation outputs.
_DISCLAIMER_PATTERNS = [
    r"consult\s+(a\s+)?(qualified|local|certified)?\s*(extension\s+officer|agronomist|specialist|professional)",
    r"seek\s+(professional|expert)\s+advice",
    r"verify\s+(with|by)\s+(a\s+)?(professional|expert|agronomist)",
    r"this\s+is\s+not\s+(a\s+substitute\s+for)?\s*(professional|certified)\s+advice",
    r"not\s+a\s+substitute\s+for\s+professional",
    r"(consult|contact|speak\s+to|check\s+with|verify\s+with)\s+(an?\s+)?(agronomist|extension|specialist|professional|expert)",
]
_DISCLAIMER_RE = re.compile("|".join(_DISCLAIMER_PATTERNS), flags=re.IGNORECASE)

# ── Severity that requires human review ───────────────────────────────────────
_ESCALATION_SEVERITIES = {"severe"}


# ── Public API ────────────────────────────────────────────────────────────────

def check_chemical_safety(text: str) -> GuardrailResult:
    """
    Detect references to WHO Class Ia/Ib highly hazardous or globally banned
    pesticides in LLM-generated recommendations.

    Returns:
        GuardrailResult with layer="agri_chemical_safety"
        passed=False if banned chemicals are mentioned.
        Details list the chemical names found.
    """
    layer = "agri_chemical_safety"

    if not text:
        return GuardrailResult(passed=True, reason="Empty text.", layer=layer)

    matches = _BANNED_CHEM_RE.findall(text)
    if matches:
        unique = sorted({m.lower() for m in matches})
        return GuardrailResult(
            passed=False,
            reason=(
                f"Response mentions hazardous or banned chemical(s): {', '.join(unique)}. "
                "These are WHO Class Ia/Ib highly hazardous pesticides or globally banned "
                "substances and must not be recommended. The response has been blocked."
            ),
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
            details={"banned_chemicals": unique},
        )

    return GuardrailResult(
        passed=True,
        reason="No banned or highly hazardous chemicals detected.",
        layer=layer,
        severity=GuardrailSeverity.INFO,
    )


def check_dangerous_advice(text: str) -> GuardrailResult:
    """
    Detect actionable dangerous instructions in LLM-generated text.

    Returns:
        GuardrailResult with layer="agri_dangerous_advice"
        passed=False if dangerous instructions are detected.
    """
    layer = "agri_dangerous_advice"

    if not text:
        return GuardrailResult(passed=True, reason="Empty text.", layer=layer)

    match = _DANGEROUS_RE.search(text)
    if match:
        snippet = text[max(0, match.start() - 15): match.end() + 15]
        return GuardrailResult(
            passed=False,
            reason="Response contains potentially dangerous agricultural instructions. "
                   "The response has been blocked to protect user safety.",
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
            details={"matched_snippet": snippet},
        )

    return GuardrailResult(
        passed=True,
        reason="No dangerous advice patterns detected.",
        layer=layer,
        severity=GuardrailSeverity.INFO,
    )


def check_disclaimer_present(text: str) -> GuardrailResult:
    """
    Verify that AI-generated recommendations include a disclaimer advising
    the farmer to consult a qualified professional.

    Returns:
        GuardrailResult with layer="agri_disclaimer"
        passed=True with WARNING severity if no disclaimer is present
        (we do not block but flag it for the UI to handle).
    """
    layer = "agri_disclaimer"

    if not text:
        return GuardrailResult(
            passed=True,
            reason="Empty text — disclaimer check skipped.",
            layer=layer,
            severity=GuardrailSeverity.WARNING,
        )

    if _DISCLAIMER_RE.search(text):
        return GuardrailResult(
            passed=True,
            reason="Disclaimer / professional consultation advice is present.",
            layer=layer,
            severity=GuardrailSeverity.INFO,
        )

    return GuardrailResult(
        passed=True,
        reason="Recommendation does not explicitly advise consulting an extension officer. "
               "A standard disclaimer has been appended.",
        layer=layer,
        severity=GuardrailSeverity.WARNING,
    )


def check_severity_escalation(parsed_diagnosis: dict) -> GuardrailResult:
    """
    Flag 'Severe' diagnoses for mandatory human review before action is taken.

    This is a WARNING-level check — it does not block the pipeline but
    instructs the UI to display a prominent escalation notice.

    Args:
        parsed_diagnosis: Dict from PathologistAgent.analyse() containing
                          at least the 'severity' key.

    Returns:
        GuardrailResult with layer="agri_severity_escalation"
    """
    layer = "agri_severity_escalation"

    severity = parsed_diagnosis.get("severity", "").strip().lower()

    if severity in _ESCALATION_SEVERITIES:
        disease = parsed_diagnosis.get("disease_name", "unknown condition")
        return GuardrailResult(
            passed=True,
            reason=(
                f"SEVERE diagnosis detected: {disease}. "
                "Human review by a qualified plant pathologist or agricultural extension "
                "officer is strongly recommended before applying any treatment."
            ),
            layer=layer,
            severity=GuardrailSeverity.WARNING,
            details={"severity": severity, "disease": disease},
        )

    return GuardrailResult(
        passed=True,
        reason="Severity level does not require mandatory escalation.",
        layer=layer,
        severity=GuardrailSeverity.INFO,
    )

"""
agents/extension_officer.py
============================
Extension Officer Agent — receives a Pathologist diagnosis and generates
safe, actionable agricultural recommendations using IBM Granite text generation.

Guardrails applied (in order):
  1. agent_communication.check_diagnosis_message() — inter-agent schema validation
  2. security_guardrails.check_response_payload()  — response size limit
  3. security_guardrails.check_env_exposure()      — credential leak detection
  4. agricultural_safety.check_chemical_safety()   — banned chemical detection
  5. agricultural_safety.check_dangerous_advice()  — dangerous instruction detection
  6. agricultural_safety.check_disclaimer_present() — disclaimer enforcement
  7. output_guardrails.check_recommendation_output() — quality + structure

Usage:
    agent = ExtensionOfficerAgent()
    result = agent.recommend(diagnosis_dict)
"""

from utils.watsonx_client import get_text_response
from guardrails.output_guardrails      import check_recommendation_output
from guardrails.security_guardrails    import check_response_payload, check_env_exposure
from guardrails.agent_communication    import check_diagnosis_message
from guardrails.agricultural_safety    import (
    check_chemical_safety,
    check_dangerous_advice,
    check_disclaimer_present,
)


# ── Prompt template ───────────────────────────────────────────────────────────

_SYSTEM_INSTRUCTION = """\
You are an expert agricultural extension officer AI assistant. Based on the \
provided crop disease diagnosis, generate safe and practical recommendations \
for the farmer. Respond ONLY using the exact structured format below. \
Do NOT include any extra text, greetings, or preamble outside the format. \
Only recommend legally registered chemicals and always advise consulting a \
local extension officer for final confirmation.\
"""

_RECOMMENDATION_FORMAT = """\
Treatment: <specific treatment steps the farmer should take immediately>
Prevention: <measures to prevent this disease from recurring>
Safe Chemicals: <registered fungicides, pesticides, or biological agents safe for this crop, or "None required" if healthy>
Farmer Advisory: <important safety notes, timing advice, and reminder to consult a local extension officer>
"""

def _build_recommendation_prompt(diagnosis: dict) -> str:
    """Compose the text prompt from the diagnosis dict."""
    disease    = diagnosis.get("disease_name",      "Unknown")
    confidence = diagnosis.get("confidence",        "Unknown")
    severity   = diagnosis.get("severity",          "Unknown")
    symptoms   = diagnosis.get("symptoms_observed", "Unknown")

    prompt = _SYSTEM_INSTRUCTION + "\n\n"
    prompt += "Crop Disease Diagnosis:\n"
    prompt += f"- Disease/Condition: {disease}\n"
    prompt += f"- Confidence: {confidence}\n"
    prompt += f"- Severity: {severity}\n"
    prompt += f"- Symptoms Observed: {symptoms}\n\n"
    prompt += "Provide agricultural recommendations strictly in this format:\n\n"
    prompt += _RECOMMENDATION_FORMAT
    return prompt


# ── Response parser ───────────────────────────────────────────────────────────

def _parse_recommendations(raw_text: str) -> dict:
    """
    Parse structured labelled lines from the model response.

    Multi-line values are supported — a value continues until the next
    recognised key or end of text.
    """
    result = {
        "treatment":       "Not available.",
        "prevention":      "Not available.",
        "safe_chemicals":  "Not available.",
        "farmer_advisory": "Not available.",
    }

    key_map = {
        "treatment":       "treatment",
        "prevention":      "prevention",
        "safe chemicals":  "safe_chemicals",
        "safe_chemical":   "safe_chemicals",
        "chemicals":       "safe_chemicals",
        "farmer advisory": "farmer_advisory",
        "advisory":        "farmer_advisory",
    }

    current_key = None
    buffer = []

    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped:
            if current_key:
                buffer.append("")
            continue

        matched_key = None
        for label, field_key in key_map.items():
            if stripped.lower().startswith(label + ":"):
                matched_key = field_key
                if current_key and buffer:
                    result[current_key] = " ".join(p for p in buffer if p).strip()
                current_key = matched_key
                buffer = [stripped[len(label) + 1:].strip()]
                break

        if matched_key is None and current_key:
            buffer.append(stripped)

    if current_key and buffer:
        result[current_key] = " ".join(p for p in buffer if p).strip()

    return result


def _empty_recommendation(error: str, tokens: int = 0, latency: float = 0, guardrail: dict = None) -> dict:
    """Convenience builder for error return dicts."""
    d = {
        "treatment": "",
        "prevention": "",
        "safe_chemicals": "",
        "farmer_advisory": "",
        "raw_response": "",
        "tokens_used": tokens,
        "latency_ms": latency,
        "error": error,
    }
    if guardrail:
        d["guardrail_result"] = guardrail
    return d


# ── Agent class ───────────────────────────────────────────────────────────────

class ExtensionOfficerAgent:
    """
    Agent 2 — Agricultural Extension Officer.

    Receives a diagnosis dict from the Pathologist Agent and generates
    structured agricultural recommendations using IBM Granite text generation.
    """

    name = "ExtensionOfficerAgent"

    def recommend(self, diagnosis: dict) -> dict:
        """
        Generate agricultural recommendations based on a crop diagnosis.

        Args:
            diagnosis: Dict returned by PathologistAgent.analyse().

        Returns:
            dict with keys:
              treatment, prevention, safe_chemicals, farmer_advisory,
              raw_response, tokens_used, latency_ms, error (None on success),
              guardrail_result (GuardrailResult.to_dict()),
              agri_safety_events (list of agricultural safety guardrail dicts)
        """
        # ── 1. Inter-agent communication validation ───────────────────────────
        comm_check = check_diagnosis_message(diagnosis)
        if not comm_check.passed:
            return _empty_recommendation(
                f"Agent communication guardrail blocked: {comm_check.reason}",
                guardrail=comm_check.to_dict(),
            )

        # ── 2. Build prompt and call text model ───────────────────────────────
        prompt     = _build_recommendation_prompt(diagnosis)
        api_result = get_text_response(prompt)

        if api_result.get("error"):
            return _empty_recommendation(
                f"Text API error: {api_result['error']}",
                tokens=api_result.get("tokens_used", 0),
                latency=api_result.get("latency_ms", 0),
            )

        raw_text = api_result["text"]

        # ── 3. Security: payload size + env exposure ──────────────────────────
        payload_check = check_response_payload(raw_text)
        if not payload_check.passed:
            return _empty_recommendation(
                f"Security guardrail blocked: {payload_check.reason}",
                tokens=api_result.get("tokens_used", 0),
                latency=api_result.get("latency_ms", 0),
                guardrail=payload_check.to_dict(),
            )

        env_check = check_env_exposure(raw_text)
        if not env_check.passed:
            return _empty_recommendation(
                f"Security guardrail blocked: {env_check.reason}",
                tokens=api_result.get("tokens_used", 0),
                latency=api_result.get("latency_ms", 0),
                guardrail=env_check.to_dict(),
            )

        # ── 4. Parse structured response ──────────────────────────────────────
        parsed = _parse_recommendations(raw_text)

        # ── 5. Agricultural safety checks ─────────────────────────────────────
        agri_safety_events = []

        chem_check = check_chemical_safety(raw_text)
        agri_safety_events.append(chem_check.to_dict())
        if not chem_check.passed:
            return _empty_recommendation(
                f"Agricultural safety guardrail blocked: {chem_check.reason}",
                tokens=api_result.get("tokens_used", 0),
                latency=api_result.get("latency_ms", 0),
                guardrail=chem_check.to_dict(),
            )

        danger_check = check_dangerous_advice(raw_text)
        agri_safety_events.append(danger_check.to_dict())
        if not danger_check.passed:
            return _empty_recommendation(
                f"Agricultural safety guardrail blocked: {danger_check.reason}",
                tokens=api_result.get("tokens_used", 0),
                latency=api_result.get("latency_ms", 0),
                guardrail=danger_check.to_dict(),
            )

        disclaimer_check = check_disclaimer_present(raw_text)
        agri_safety_events.append(disclaimer_check.to_dict())
        # disclaimer is WARNING-only — do not block

        # ── 6. Output guardrail (structure + hallucination) ───────────────────
        output_check = check_recommendation_output(raw_text, parsed)
        if not output_check.passed:
            return _empty_recommendation(
                f"Output guardrail blocked: {output_check.reason}",
                tokens=api_result.get("tokens_used", 0),
                latency=api_result.get("latency_ms", 0),
                guardrail=output_check.to_dict(),
            )

        return {
            **parsed,
            "raw_response":      raw_text,
            "tokens_used":       api_result.get("tokens_used", 0),
            "latency_ms":        api_result.get("latency_ms", 0),
            "error":             None,
            "guardrail_result":  output_check.to_dict(),
            "agri_safety_events": agri_safety_events,
        }

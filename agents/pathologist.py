"""
agents/pathologist.py
======================
Pathologist Agent — analyses a base64-encoded crop image and returns a
structured disease diagnosis using IBM Granite Vision.

Guardrails applied (in order):
  1. input_guardrails.check_text()          — farmer note injection/PII/length
  2. security_guardrails.check_response_payload() — response size limit
  3. security_guardrails.check_env_exposure()     — credential leak detection
  4. output_guardrails.check_diagnosis_output()   — quality + structure + hallucination

Usage:
    agent = PathologistAgent()
    result = agent.analyse(image_b64, farmer_note="Leaves yellowing")
"""

from utils.watsonx_client import get_vision_response
from guardrails.input_guardrails    import check_text
from guardrails.output_guardrails   import check_diagnosis_output
from guardrails.security_guardrails import check_response_payload, check_env_exposure


# ── Prompt template ───────────────────────────────────────────────────────────

_SYSTEM_INSTRUCTION = """\
You are an expert plant pathologist AI assistant. Your task is to analyse the \
provided crop image and identify any visible disease, pest damage, nutrient \
deficiency, or abnormality. Respond ONLY using the exact structured format below. \
Do NOT include any extra text, greetings, or explanations outside the format.\
"""

_DIAGNOSIS_FORMAT = """\
Disease: <name of disease, pest, deficiency, or "Healthy — No Disease Detected">
Confidence: <percentage from 0% to 100%>
Severity: <one of: Mild | Moderate | Severe | None>
Symptoms Observed: <comma-separated list of visible symptoms on the plant/leaves/stem/fruit>
"""

def _build_vision_prompt(farmer_note: str) -> str:
    """Compose the full text prompt for the vision call."""
    prompt = _SYSTEM_INSTRUCTION + "\n\n"
    if farmer_note.strip():
        prompt += f"Farmer's note: {farmer_note.strip()}\n\n"
    prompt += "Analyse the crop image and respond strictly in this format:\n\n"
    prompt += _DIAGNOSIS_FORMAT
    return prompt


# ── Response parser ───────────────────────────────────────────────────────────

def _parse_diagnosis(raw_text: str) -> dict:
    """
    Parse structured lines from the model response.

    Expected format:
        Disease: <value>
        Confidence: <value>
        Severity: <value>
        Symptoms Observed: <value>

    Returns a dict with normalised keys. Falls back to "Unknown" if a field
    is not found.
    """
    result = {
        "disease_name":      "Unknown",
        "confidence":        "Unknown",
        "severity":          "Unknown",
        "symptoms_observed": "Unknown",
    }

    for line in raw_text.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key   = key.strip().lower()
        value = value.strip()

        if "disease" in key:
            result["disease_name"] = value
        elif "confidence" in key:
            result["confidence"] = value
        elif "severity" in key:
            result["severity"] = value
        elif "symptom" in key:
            result["symptoms_observed"] = value

    return result


def _empty_diagnosis(error: str, tokens: int = 0, latency: float = 0, guardrail: dict = None) -> dict:
    """Convenience builder for error return dicts."""
    d = {
        "disease_name": "",
        "confidence": "",
        "severity": "",
        "symptoms_observed": "",
        "raw_response": "",
        "tokens_used": tokens,
        "latency_ms": latency,
        "error": error,
    }
    if guardrail:
        d["guardrail_result"] = guardrail
    return d


# ── Agent class ───────────────────────────────────────────────────────────────

class PathologistAgent:
    """
    Agent 1 — Crop Disease Pathologist.

    Accepts a base64-encoded crop image and an optional farmer note,
    calls IBM Granite Vision, and returns a structured diagnosis dict.
    """

    name = "PathologistAgent"

    def analyse(self, image_b64: str, farmer_note: str = "") -> dict:
        """
        Analyse a crop image for diseases.

        Args:
            image_b64:   Base64-encoded JPEG string (no data URI prefix).
            farmer_note: Optional contextual note from the farmer (max 500 chars).

        Returns:
            dict with keys:
              disease_name, confidence, severity, symptoms_observed,
              raw_response, tokens_used, latency_ms, error (None on success),
              guardrail_result (GuardrailResult.to_dict())
        """
        # ── 1. Input guardrail on text note ──────────────────────────────────
        if farmer_note.strip():
            text_check = check_text(farmer_note)
            if not text_check.passed:
                return _empty_diagnosis(
                    f"Input guardrail blocked: {text_check.reason}",
                    guardrail=text_check.to_dict(),
                )

        # ── 2. Build prompt and call vision model ─────────────────────────────
        prompt     = _build_vision_prompt(farmer_note)
        api_result = get_vision_response(image_b64, prompt)

        if api_result.get("error"):
            return _empty_diagnosis(
                f"Vision API error: {api_result['error']}",
                tokens=api_result.get("tokens_used", 0),
                latency=api_result.get("latency_ms", 0),
            )

        raw_text = api_result["text"]

        # ── 3. Security: payload size + env exposure ──────────────────────────
        payload_check = check_response_payload(raw_text)
        if not payload_check.passed:
            return _empty_diagnosis(
                f"Security guardrail blocked: {payload_check.reason}",
                tokens=api_result.get("tokens_used", 0),
                latency=api_result.get("latency_ms", 0),
                guardrail=payload_check.to_dict(),
            )

        env_check = check_env_exposure(raw_text)
        if not env_check.passed:
            return _empty_diagnosis(
                f"Security guardrail blocked: {env_check.reason}",
                tokens=api_result.get("tokens_used", 0),
                latency=api_result.get("latency_ms", 0),
                guardrail=env_check.to_dict(),
            )

        # ── 4. Parse structured response ─────────────────────────────────────
        parsed = _parse_diagnosis(raw_text)

        # ── 5. Output guardrail (quality + structure + hallucination) ─────────
        output_check = check_diagnosis_output(raw_text, parsed)
        if not output_check.passed:
            return _empty_diagnosis(
                f"Output guardrail blocked: {output_check.reason}",
                tokens=api_result.get("tokens_used", 0),
                latency=api_result.get("latency_ms", 0),
                guardrail=output_check.to_dict(),
            )

        return {
            **parsed,
            "raw_response":    raw_text,
            "tokens_used":     api_result.get("tokens_used", 0),
            "latency_ms":      api_result.get("latency_ms", 0),
            "error":           None,
            "guardrail_result": output_check.to_dict(),
        }

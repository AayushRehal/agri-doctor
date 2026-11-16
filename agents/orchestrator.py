"""
agents/orchestrator.py
=======================
Multi-Agent Orchestrator for Agri Doctor.

Full guardrail pipeline (in order):
  1.  security_guardrails.check_rate_limit()       — session/window call budget
  2.  security_guardrails.sanitise_user_input()    — HTML strip, control chars
  3.  input_guardrails.check_image()               — MIME, size, dimensions
  4.  input_guardrails.check_text()                — injection, flooding, homoglyph
  5.  input_guardrails.check_pii()                 — PII detection
  6.  image_utils.*                                — load, resize, encode
  7.  PathologistAgent.analyse()                   — vision diagnosis
       └─ internal: check_response_payload, check_env_exposure, check_diagnosis_output
  8.  agricultural_safety.check_severity_escalation() — escalation flag
  9.  security_guardrails.check_execution_budget() — Pathologist latency
  10. ExtensionOfficerAgent.recommend()            — text recommendations
       └─ internal: check_diagnosis_message, check_chemical_safety,
                    check_dangerous_advice, check_disclaimer_present,
                    check_recommendation_output
  11. security_guardrails.check_execution_budget() — Extension Officer latency
  12. security_guardrails.mask_secrets()           — sanitise raw responses

Telemetry written to st.session_state:
  "eval_log"      — list of per-agent metric dicts (latency, tokens, errors, guardrails)
  "run_log"       — list of per-run summary dicts consumed by the dashboard

Usage:
    orchestrator = Orchestrator()
    result = orchestrator.run(uploaded_file, farmer_note="Yellowing leaves")
"""

import time
import uuid
from datetime import datetime

import streamlit as st

from agents.pathologist            import PathologistAgent
from agents.extension_officer      import ExtensionOfficerAgent
from guardrails.input_guardrails   import check_image, check_text, check_pii
from guardrails.security_guardrails import (
    sanitise_user_input,
    mask_secrets,
    check_rate_limit,
    check_execution_budget,
)
from guardrails.agricultural_safety import check_severity_escalation
from utils.image_utils import load_and_validate_image, encode_image_base64

# ── Session state initialiser ─────────────────────────────────────────────────

def _init_session_state():
    """Ensure eval_log and run_log exist in session_state."""
    if "eval_log" not in st.session_state:
        st.session_state["eval_log"] = []
    if "run_log" not in st.session_state:
        st.session_state["run_log"] = []


# ── Orchestrator ──────────────────────────────────────────────────────────────

class Orchestrator:
    """
    Multi-Agent Orchestrator.

    Manages the full analysis pipeline from raw image upload through to
    combined diagnosis + recommendations, while recording metrics in
    st.session_state["eval_log"].
    """

    def run(self, uploaded_file, farmer_note: str = "") -> dict:
        """
        Execute the full Agri Doctor agent pipeline.

        Args:
            uploaded_file: Streamlit UploadedFile (crop image).
            farmer_note:   Optional text note from the farmer.

        Returns:
            dict with keys:
              run_id, timestamp, diagnosis, recommendations,
              guardrail_events, agri_safety_events, escalation_events,
              error (None on success)
        """
        _init_session_state()

        run_id      = uuid.uuid4().hex[:8]
        timestamp   = datetime.now().isoformat()
        pipeline_t0 = time.perf_counter()
        guardrail_events   = []
        escalation_events  = []

        # ── Step 1: Rate limit ────────────────────────────────────────────────
        rate_check = check_rate_limit(st.session_state)
        guardrail_events.append(rate_check.to_dict())
        if not rate_check.passed:
            self._log_metrics(run_id, timestamp, "security_rate_limit", 0, 0, 1, True)
            return self._abort(run_id, timestamp, guardrail_events, rate_check.reason)

        # ── Step 2: Security guardrail — sanitise text ────────────────────────
        clean_note = sanitise_user_input(farmer_note)

        # ── Step 3: Input guardrail — validate image ──────────────────────────
        img_check = check_image(uploaded_file)
        guardrail_events.append(img_check.to_dict())
        if not img_check.passed:
            self._log_metrics(run_id, timestamp, "input_guardrail", 0, 0, 1, True)
            return self._abort(run_id, timestamp, guardrail_events, img_check.reason)

        # ── Step 4: Input guardrail — validate farmer note ────────────────────
        if clean_note.strip():
            text_check = check_text(clean_note)
            guardrail_events.append(text_check.to_dict())
            if not text_check.passed:
                self._log_metrics(run_id, timestamp, "input_guardrail", 0, 0, 1, True)
                return self._abort(run_id, timestamp, guardrail_events, text_check.reason)

            # ── Step 5: PII detection ─────────────────────────────────────────
            pii_check = check_pii(clean_note)
            guardrail_events.append(pii_check.to_dict())
            if not pii_check.passed:
                self._log_metrics(run_id, timestamp, "input_guardrail", 0, 0, 1, True)
                return self._abort(run_id, timestamp, guardrail_events, pii_check.reason)

        # ── Step 6: Load, validate, and encode the image ──────────────────────
        try:
            pil_image = load_and_validate_image(uploaded_file)
            image_b64 = encode_image_base64(pil_image)
        except ValueError as exc:
            return self._abort(run_id, timestamp, guardrail_events, str(exc))

        # ── Step 7: Pathologist Agent ─────────────────────────────────────────
        pathologist = PathologistAgent()
        diagnosis   = pathologist.analyse(image_b64, clean_note)

        if "guardrail_result" in diagnosis:
            guardrail_events.append(diagnosis["guardrail_result"])

        path_latency = diagnosis.get("latency_ms", 0)
        self._log_metrics(
            run_id, timestamp, PathologistAgent.name,
            latency_ms    = path_latency,
            tokens_used   = diagnosis.get("tokens_used", 0),
            guardrail_hits = 1 if diagnosis.get("error") and "guardrail" in str(diagnosis.get("error", "")).lower() else 0,
            has_error     = bool(diagnosis.get("error")),
        )

        # ── Step 8: Agricultural severity escalation ──────────────────────────
        if not diagnosis.get("error"):
            esc_check = check_severity_escalation(diagnosis)
            escalation_events.append(esc_check.to_dict())

        # ── Step 9: Execution budget — Pathologist ────────────────────────────
        budget_check = check_execution_budget(path_latency, PathologistAgent.name)
        guardrail_events.append(budget_check.to_dict())
        # Budget BLOCK is recorded but does not abort (result already received)

        # ── Step 10: Extension Officer Agent ──────────────────────────────────
        ext_officer     = ExtensionOfficerAgent()
        recommendations = ext_officer.recommend(diagnosis)

        if "guardrail_result" in recommendations:
            guardrail_events.append(recommendations["guardrail_result"])

        ext_latency = recommendations.get("latency_ms", 0)
        self._log_metrics(
            run_id, timestamp, ExtensionOfficerAgent.name,
            latency_ms    = ext_latency,
            tokens_used   = recommendations.get("tokens_used", 0),
            guardrail_hits = 1 if recommendations.get("error") and "guardrail" in str(recommendations.get("error", "")).lower() else 0,
            has_error     = bool(recommendations.get("error")),
        )

        # ── Step 11: Execution budget — Extension Officer ──────────────────────
        ext_budget_check = check_execution_budget(ext_latency, ExtensionOfficerAgent.name)
        guardrail_events.append(ext_budget_check.to_dict())

        # ── Step 12: Security — mask any secrets in raw responses ──────────────
        if diagnosis.get("raw_response"):
            diagnosis["raw_response"] = mask_secrets(diagnosis["raw_response"])
        if recommendations.get("raw_response"):
            recommendations["raw_response"] = mask_secrets(recommendations["raw_response"])

        # Collect agri safety events from extension officer
        agri_safety_events = recommendations.pop("agri_safety_events", [])

        pipeline_ms  = round((time.perf_counter() - pipeline_t0) * 1000, 1)
        pipeline_err = diagnosis.get("error") or recommendations.get("error")

        # ── Write run-level telemetry record ──────────────────────────────────
        # Counts all guardrail events across both input and output layers.
        total_guardrail_hits = sum(
            1 for e in guardrail_events if not e.get("passed", True)
        )
        # Hallucination score from the output guardrail detail dict (if present)
        hall_score = 0
        for ev in guardrail_events:
            if ev.get("layer") in ("output_response", "output_diagnosis",
                                   "output_recommendation"):
                hall_score = max(hall_score,
                                 ev.get("details", {}).get("hallucination_score", 0))

        self._log_run(
            run_id           = run_id,
            timestamp        = timestamp,
            pipeline_ms      = pipeline_ms,
            path_latency_ms  = path_latency,
            ext_latency_ms   = ext_latency,
            path_tokens      = diagnosis.get("tokens_used", 0),
            ext_tokens       = recommendations.get("tokens_used", 0),
            path_error       = bool(diagnosis.get("error")),
            ext_error        = bool(recommendations.get("error")),
            handoff_success  = not bool(diagnosis.get("error")),
            guardrail_hits   = total_guardrail_hits,
            hallucination_score = hall_score,
            severity         = diagnosis.get("severity", ""),
            disease          = diagnosis.get("disease_name", ""),
        )

        return {
            "run_id":              run_id,
            "timestamp":           timestamp,
            "diagnosis":           diagnosis,
            "recommendations":     recommendations,
            "guardrail_events":    guardrail_events,
            "escalation_events":   escalation_events,
            "agri_safety_events":  agri_safety_events,
            "error": pipeline_err,
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _abort(run_id: str, timestamp: str, guardrail_events: list, reason: str) -> dict:
        """Construct a standard abort response and write an aborted run record."""
        _init_session_state()
        st.session_state["run_log"].append({
            "run_id":             run_id,
            "timestamp":          timestamp,
            "pipeline_ms":        0,
            "path_latency_ms":    0,
            "ext_latency_ms":     0,
            "path_tokens":        0,
            "ext_tokens":         0,
            "path_error":         True,
            "ext_error":          True,
            "handoff_success":    False,
            "guardrail_hits":     sum(1 for e in guardrail_events
                                      if not e.get("passed", True)),
            "hallucination_score": 0,
            "severity":           "",
            "disease":            "",
            "aborted":            True,
            "abort_reason":       reason,
        })
        return {
            "run_id":             run_id,
            "timestamp":          timestamp,
            "diagnosis":          {},
            "recommendations":    {},
            "guardrail_events":   guardrail_events,
            "escalation_events":  [],
            "agri_safety_events": [],
            "error":              reason,
        }

    @staticmethod
    def _log_metrics(
        run_id: str,
        timestamp: str,
        agent: str,
        latency_ms: float,
        tokens_used: int,
        guardrail_hits: int,
        has_error: bool,
    ):
        """Append a per-agent metrics record to st.session_state["eval_log"]."""
        _init_session_state()
        st.session_state["eval_log"].append({
            "run_id":          run_id,
            "timestamp":       timestamp,
            "agent":           agent,
            "latency_ms":      latency_ms,
            "tokens_used":     tokens_used,
            "guardrail_hits":  guardrail_hits,
            "error":           has_error,
        })

    @staticmethod
    def _log_run(
        run_id: str,
        timestamp: str,
        pipeline_ms: float,
        path_latency_ms: float,
        ext_latency_ms: float,
        path_tokens: int,
        ext_tokens: int,
        path_error: bool,
        ext_error: bool,
        handoff_success: bool,
        guardrail_hits: int,
        hallucination_score: int,
        severity: str,
        disease: str,
    ):
        """Append a per-run summary record to st.session_state["run_log"]."""
        _init_session_state()
        st.session_state["run_log"].append({
            "run_id":              run_id,
            "timestamp":           timestamp,
            "pipeline_ms":         pipeline_ms,
            "path_latency_ms":     path_latency_ms,
            "ext_latency_ms":      ext_latency_ms,
            "path_tokens":         path_tokens,
            "ext_tokens":          ext_tokens,
            "path_error":          path_error,
            "ext_error":           ext_error,
            "handoff_success":     handoff_success,
            "guardrail_hits":      guardrail_hits,
            "hallucination_score": hallucination_score,
            "severity":            severity,
            "disease":             disease,
            "aborted":             False,
            "abort_reason":        "",
        })

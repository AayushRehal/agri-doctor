"""
guardrails/security_guardrails.py
==================================
Security-focused guardrails for Agri Doctor.

Checks implemented:
  1.  API credential masking in log/response text
  2.  User-input sanitisation (HTML, control chars)
  3.  Rate limiting (per-session call budget)
  4.  Execution time budget (per-agent wall-clock limit)
  5.  API response payload size limit
  6.  Environment variable exposure prevention

Public API:
  mask_secrets(text)                     -> str
  sanitise_user_input(text)              -> str
  check_rate_limit(session_state)        -> GuardrailResult
  check_execution_budget(elapsed_ms)     -> GuardrailResult
  check_response_payload(text)           -> GuardrailResult
  check_env_exposure(text)               -> GuardrailResult
"""

import re
import html
import time
from guardrails import GuardrailResult, GuardrailSeverity

# ── Rate limit constants ───────────────────────────────────────────────────────
MAX_CALLS_PER_SESSION  = 50     # max total Orchestrator.run() calls in one session
RATE_LIMIT_WINDOW_S    = 60     # sliding window in seconds
MAX_CALLS_PER_WINDOW   = 10     # max calls within that window

# ── Execution budget constants ─────────────────────────────────────────────────
MAX_AGENT_LATENCY_MS   = 60_000  # 60 s per agent call before we flag it
WARN_AGENT_LATENCY_MS  = 30_000  # 30 s — emit WARNING before blocking

# ── Payload size constants ─────────────────────────────────────────────────────
MAX_RESPONSE_CHARS     = 20_000  # ~20 KB of text — abnormally large responses

# ── Credential / secret patterns ──────────────────────────────────────────────
_SECRET_PREFIX = r"(?:api[_\-]?key|token|secret|password|apikey|credential)[\"'\s:=]+?"
_SECRET_VALUE  = r"[A-Za-z0-9_\-]{32,}"
_SECRET_RE     = re.compile(rf"({_SECRET_PREFIX})({_SECRET_VALUE})", flags=re.IGNORECASE)
_LONG_TOKEN_RE = re.compile(r"\b([A-Za-z0-9_\-]{40,})\b")

# ── Environment variable name patterns ────────────────────────────────────────
# Detect responses that accidentally echo back env var values
_ENV_EXPOSE_RE = re.compile(
    r"(WATSONX_API_KEY|WATSONX_PROJECT_ID|WATSONX_URL|IBM_API_KEY)\s*[=:]\s*\S+",
    flags=re.IGNORECASE,
)

# ── HTML / control character patterns ─────────────────────────────────────────
_HTML_TAG_RE     = re.compile(r"<[^>]+>")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


# ── Public API ────────────────────────────────────────────────────────────────

def mask_secrets(text: str) -> str:
    """
    Redact API key-like patterns in a string before it reaches logs or the UI.

    Two passes:
      1. Prefix + value patterns  (e.g. api_key: <32+ chars>)
      2. Standalone IBM IAM-style tokens (40+ chars)

    Returns:
        String with secret values replaced by [REDACTED].
    """
    if not text:
        return text

    result = _SECRET_RE.sub(lambda m: m.group(1) + "[REDACTED]", text)

    def _redact_long(match: re.Match) -> str:
        token = match.group(1)
        if len(token) >= 40 and not token.startswith("http"):
            return "[REDACTED]"
        return token

    result = _LONG_TOKEN_RE.sub(_redact_long, result)
    return result


def sanitise_user_input(text: str) -> str:
    """
    Strip potentially dangerous content from user-supplied text.

    Steps:
      1. Unescape HTML entities
      2. Remove HTML tags
      3. Remove control characters (keeping standard whitespace)
      4. Strip leading/trailing whitespace

    Returns:
        Sanitised string safe for use in LLM prompts.
    """
    if not text:
        return ""
    cleaned = html.unescape(text)
    cleaned = _HTML_TAG_RE.sub("", cleaned)
    cleaned = _CONTROL_CHAR_RE.sub("", cleaned)
    return cleaned.strip()


def check_rate_limit(session_state: dict) -> GuardrailResult:
    """
    Enforce a per-session and sliding-window rate limit on Orchestrator calls.

    Uses two counters stored in session_state:
      - "security_total_calls"      : int  — lifetime call count this session
      - "security_call_timestamps"  : list — Unix timestamps of recent calls

    Args:
        session_state: Streamlit st.session_state (or any dict-like object).

    Returns:
        GuardrailResult with layer="security_rate_limit"
    """
    layer = "security_rate_limit"
    now   = time.time()

    # Initialise counters
    if "security_total_calls" not in session_state:
        session_state["security_total_calls"] = 0
    if "security_call_timestamps" not in session_state:
        session_state["security_call_timestamps"] = []

    total = session_state["security_total_calls"]

    # 1. Session-lifetime limit
    if total >= MAX_CALLS_PER_SESSION:
        return GuardrailResult(
            passed=False,
            reason=f"Session limit of {MAX_CALLS_PER_SESSION} analyses has been reached. "
                   "Please refresh the page to start a new session.",
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
            details={"total_calls": total, "limit": MAX_CALLS_PER_SESSION},
        )

    # 2. Sliding-window rate limit
    timestamps: list = session_state["security_call_timestamps"]
    recent = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW_S]
    session_state["security_call_timestamps"] = recent  # prune old entries

    if len(recent) >= MAX_CALLS_PER_WINDOW:
        wait_s = int(RATE_LIMIT_WINDOW_S - (now - min(recent))) + 1
        return GuardrailResult(
            passed=False,
            reason=f"Rate limit: {MAX_CALLS_PER_WINDOW} analyses per {RATE_LIMIT_WINDOW_S}s window. "
                   f"Please wait approximately {wait_s} second(s).",
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
            details={"calls_in_window": len(recent), "wait_seconds": wait_s},
        )

    # Update counters
    session_state["security_total_calls"] = total + 1
    session_state["security_call_timestamps"] = recent + [now]

    return GuardrailResult(
        passed=True,
        reason=f"Rate limit OK ({len(recent) + 1}/{MAX_CALLS_PER_WINDOW} calls in window, "
               f"{total + 1}/{MAX_CALLS_PER_SESSION} session total).",
        layer=layer,
        severity=GuardrailSeverity.INFO,
        details={"total_calls": total + 1, "calls_in_window": len(recent) + 1},
    )


def check_execution_budget(elapsed_ms: float, agent_name: str = "") -> GuardrailResult:
    """
    Check whether an agent call exceeded the allowed execution time budget.

    Returns WARNING at WARN_AGENT_LATENCY_MS, BLOCK at MAX_AGENT_LATENCY_MS.

    Args:
        elapsed_ms: Wall-clock time the agent call took, in milliseconds.
        agent_name: Optional name for the log entry.

    Returns:
        GuardrailResult with layer="security_execution_budget"
    """
    layer = "security_execution_budget"
    label = f" ({agent_name})" if agent_name else ""

    if elapsed_ms >= MAX_AGENT_LATENCY_MS:
        return GuardrailResult(
            passed=False,
            reason=f"Agent call{label} took {elapsed_ms/1000:.1f}s, exceeding the "
                   f"{MAX_AGENT_LATENCY_MS/1000:.0f}s execution budget.",
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
            details={"elapsed_ms": elapsed_ms, "limit_ms": MAX_AGENT_LATENCY_MS},
        )

    if elapsed_ms >= WARN_AGENT_LATENCY_MS:
        return GuardrailResult(
            passed=True,
            reason=f"Agent call{label} took {elapsed_ms/1000:.1f}s — above the "
                   f"{WARN_AGENT_LATENCY_MS/1000:.0f}s warning threshold. "
                   "Response may be slow.",
            layer=layer,
            severity=GuardrailSeverity.WARNING,
            details={"elapsed_ms": elapsed_ms, "warn_ms": WARN_AGENT_LATENCY_MS},
        )

    return GuardrailResult(
        passed=True,
        reason=f"Execution budget OK{label}: {elapsed_ms:.0f} ms.",
        layer=layer,
        severity=GuardrailSeverity.INFO,
        details={"elapsed_ms": elapsed_ms},
    )


def check_response_payload(text: str) -> GuardrailResult:
    """
    Reject abnormally large LLM responses that may indicate prompt stuffing or
    runaway generation.

    Args:
        text: Raw text from the model.

    Returns:
        GuardrailResult with layer="security_payload_size"
    """
    layer = "security_payload_size"

    if not text:
        return GuardrailResult(passed=True, reason="Empty payload.", layer=layer)

    char_count = len(text)
    if char_count > MAX_RESPONSE_CHARS:
        return GuardrailResult(
            passed=False,
            reason=f"Response payload is abnormally large ({char_count:,} chars, limit {MAX_RESPONSE_CHARS:,}). "
                   "The response has been discarded.",
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
            details={"char_count": char_count, "limit": MAX_RESPONSE_CHARS},
        )

    return GuardrailResult(
        passed=True,
        reason=f"Payload size OK: {char_count:,} chars.",
        layer=layer,
        severity=GuardrailSeverity.INFO,
        details={"char_count": char_count},
    )


def check_env_exposure(text: str) -> GuardrailResult:
    """
    Detect if a model response accidentally echoes environment variable values.

    Returns:
        GuardrailResult with layer="security_env_exposure"
        passed=False if env variable names and values appear in the text.
    """
    layer = "security_env_exposure"

    if not text:
        return GuardrailResult(passed=True, reason="Empty text.", layer=layer)

    if _ENV_EXPOSE_RE.search(text):
        return GuardrailResult(
            passed=False,
            reason="Response appears to contain environment variable values. "
                   "The response has been blocked to prevent credential exposure.",
            layer=layer,
            severity=GuardrailSeverity.BLOCK,
        )

    return GuardrailResult(
        passed=True,
        reason="No environment variable exposure detected.",
        layer=layer,
        severity=GuardrailSeverity.INFO,
    )

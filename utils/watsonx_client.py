"""
utils/watsonx_client.py
=======================
IBM watsonx.ai client wrapper for Agri Doctor.

Public API
──────────
  get_text_response(prompt, params)              -> dict
  get_vision_response(image_b64, prompt, params) -> dict
  check_credentials()                            -> (bool, str)

Both response functions return: {text, tokens_used, latency_ms, error}

Credential loading
──────────────────
Credentials are read ONLY from AgriDoctor/.env via python-dotenv.
st.secrets is intentionally NOT used — it requires a secrets.toml to be
present at a Streamlit-controlled path and raises an exception when the
file is absent, which was causing false credential failures.

The .env path is resolved relative to THIS file's directory, so it works
regardless of which directory Streamlit sets as cwd.
"""

import os
import time
from functools import lru_cache
from dotenv import load_dotenv, dotenv_values

# ── Absolute path to AgriDoctor/.env ─────────────────────────────────────────
# Resolved from __file__ so it is cwd-independent.
# utils/watsonx_client.py  ->  utils/  ->  AgriDoctor/ (or repo root)  ->  .env
_HERE     = os.path.dirname(os.path.abspath(__file__))   # .../utils/
_ROOT     = os.path.dirname(_HERE)                        # .../AgriDoctor/ or repo root

# Search for .env in _ROOT first, then one level up (handles both repo layouts)
_ENV_PATH = os.path.join(_ROOT, ".env")
if not os.path.isfile(_ENV_PATH):
    _ENV_PATH = os.path.join(os.path.dirname(_ROOT), ".env")

# Load .env into os.environ immediately at import time.
# override=True: .env always wins over any OS-level env vars.
load_dotenv(_ENV_PATH, override=True)

# ── Model IDs ─────────────────────────────────────────────────────────────────
# Read AFTER load_dotenv so the .env values are already in os.environ.
VISION_MODEL_ID = os.getenv("WATSONX_VISION_MODEL", "ibm/granite-vision-3-2-2b").strip()
TEXT_MODEL_ID   = os.getenv("WATSONX_MODEL_ID",     "ibm/granite-vision-3-2-2b").strip()
MODEL_ID        = VISION_MODEL_ID   # legacy alias

# ── Generation parameters (OpenAI-compatible chat API param names) ────────────
DEFAULT_PARAMS = {
    "max_tokens": 512,
    "temperature": 0.1,
    "top_p": 0.9,
}


# ── Credential loader ─────────────────────────────────────────────────────────

def _load_credentials() -> dict:
    """
    Load credentials with the following resolution order:

      1. AgriDoctor/.env  — used for local development (read directly from file)
      2. os.environ       — used on Streamlit Cloud (Streamlit injects Secrets
                            into the process environment before the app starts)

    Raises RuntimeError when a required key is absent from both sources.
    """
    # Read .env file directly (empty dict if file doesn't exist on Cloud)
    file_vals = dotenv_values(_ENV_PATH) if os.path.isfile(_ENV_PATH) else {}

    def _get(key: str, default: str = "") -> str:
        # 1. .env file value (local dev)
        v = file_vals.get(key, "").strip()
        if v:
            return v
        # 2. os.environ (Streamlit Cloud injects secrets here)
        v = os.environ.get(key, "").strip()
        if v:
            return v
        return default

    api_key    = _get("WATSONX_API_KEY")
    project_id = _get("WATSONX_PROJECT_ID")
    url        = _get("WATSONX_URL", "https://us-south.ml.cloud.ibm.com")

    missing = []
    if not api_key:
        missing.append("WATSONX_API_KEY")
    if not project_id:
        missing.append("WATSONX_PROJECT_ID")

    if missing:
        raise RuntimeError(
            f"Missing credential(s): {', '.join(missing)}. "
            f"Add them to AgriDoctor/.env (local) or Streamlit Cloud Secrets."
        )

    return {"api_key": api_key, "project_id": project_id, "url": url}


# ── Cached SDK client factories ───────────────────────────────────────────────
# lru_cache keeps one client per model alive for the Streamlit session.
# The cache is keyed on the credential values so a stale client is never
# reused if credentials change between runs.

@lru_cache(maxsize=4)
def _build_client(model_id: str, api_key: str, project_id: str, url: str):
    """
    Create a ModelInference client for the given model + credentials.

    Keyed on all four arguments so lru_cache naturally invalidates when
    credentials change.  validate=False skips the eager foundation_model_specs
    call that requires the project to be WML-associated.
    """
    from ibm_watsonx_ai import Credentials
    from ibm_watsonx_ai.foundation_models import ModelInference

    credentials = Credentials(api_key=api_key, url=url)
    return ModelInference(
        model_id=model_id,
        credentials=credentials,
        project_id=project_id,
        validate=False,
    )


def _get_vision_client():
    creds = _load_credentials()
    return _build_client(
        VISION_MODEL_ID,
        creds["api_key"],
        creds["project_id"],
        creds["url"],
    )


def _get_text_client():
    creds = _load_credentials()
    return _build_client(
        TEXT_MODEL_ID,
        creds["api_key"],
        creds["project_id"],
        creds["url"],
    )


# Legacy alias
def _get_model_client():
    return _get_vision_client()


# ── Public API ────────────────────────────────────────────────────────────────

def get_text_response(prompt: str, params: dict = None) -> dict:
    """
    Send a text-only prompt to the text model via chat().

    Returns: {text, tokens_used, latency_ms, error}
    """
    gen_params = {**DEFAULT_PARAMS, **(params or {})}
    t0 = time.perf_counter()
    try:
        model = _get_text_client()
        raw   = model.chat(
            messages=[{"role": "user", "content": prompt}],
            params=gen_params,
        )
        latency_ms  = round((time.perf_counter() - t0) * 1000, 1)
        text        = (raw.get("choices", [{}])[0]
                       .get("message", {}).get("content", ""))
        tokens_used = raw.get("usage", {}).get("completion_tokens", 0)
        return {"text": text.strip(), "tokens_used": tokens_used,
                "latency_ms": latency_ms, "error": None}
    except Exception as exc:
        return {"text": "", "tokens_used": 0,
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                "error": str(exc)}


def get_vision_response(image_b64: str, prompt: str, params: dict = None) -> dict:
    """
    Send an image + prompt to the vision model via chat().

    Returns: {text, tokens_used, latency_ms, error}
    """
    gen_params = {**DEFAULT_PARAMS, **(params or {})}
    t0 = time.perf_counter()
    try:
        model    = _get_vision_client()
        messages = [{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                {"type": "text", "text": prompt},
            ],
        }]
        raw         = model.chat(messages=messages, params=gen_params)
        latency_ms  = round((time.perf_counter() - t0) * 1000, 1)
        text        = (raw.get("choices", [{}])[0]
                       .get("message", {}).get("content", ""))
        tokens_used = raw.get("usage", {}).get("completion_tokens", 0)
        return {"text": text.strip(), "tokens_used": tokens_used,
                "latency_ms": latency_ms, "error": None}
    except Exception as exc:
        return {"text": "", "tokens_used": 0,
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                "error": str(exc)}


def check_credentials() -> tuple[bool, str]:
    """
    Check that AgriDoctor/.env contains the required keys.
    Pure file read — no network call, no SDK, no st.secrets.
    Called by app.py on every page render to show/hide the warning banner.
    """
    try:
        _load_credentials()
        return True, ""
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, f"Credential check failed: {exc}"

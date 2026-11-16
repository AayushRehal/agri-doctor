# Agri Doctor — Complete Development Plan

## Top-Level Overview

**Goal:** Build a fully modular, agentic AI web application called **Agri Doctor** using Python,
Streamlit, IBM watsonx.ai, and the `ibm/granite-vision-3-2-2b` model for both vision (crop image
analysis) and text (recommendation generation) tasks.

**Scope:**
- Two specialised agents (Pathologist, Extension Officer) orchestrated by a multi-agent coordinator
- Input/output guardrails and security guardrails
- An in-app LLM Evaluation Dashboard (dedicated Streamlit tab)
- Downloadable Markdown reports
- All credentials loaded from a `.env` file via `python-dotenv`

**Non-Goals:**
- No separate backend service or REST API
- No PDF generation
- No database persistence (session-state only)
- No user authentication / login system

**Single entry point:** `streamlit run app.py` from inside `AgriDoctor/`

---

## Project Structure

```
AgriDoctor/
├── app.py                          # Streamlit entry point — multi-tab UI
├── .env                            # API credentials (never committed)
├── .env.example                    # Template for credentials
├── requirements.txt                # Python dependencies
├── agents/
│   ├── __init__.py
│   ├── pathologist.py              # Agent 1 — image + text diagnosis
│   ├── extension_officer.py        # Agent 2 — recommendation generation
│   └── orchestrator.py             # Multi-agent coordinator + session log
├── guardrails/
│   ├── __init__.py
│   ├── input_guardrails.py         # Validate uploaded image + text inputs
│   ├── output_guardrails.py        # Validate / sanitise LLM responses
│   └── security_guardrails.py      # Credential masking, data sanitisation
├── evaluation/
│   ├── __init__.py
│   └── metrics_tracker.py          # Latency, token usage, errors, guardrail hits
├── utils/
│   ├── __init__.py
│   ├── watsonx_client.py           # Shared IBM watsonx.ai API wrapper
│   ├── image_utils.py              # Image loading, resizing, base64 encoding
│   └── report_generator.py         # Markdown report builder
└── ui/
    ├── __init__.py
    ├── home_tab.py                 # Image upload + diagnosis tab
    ├── recommendations_tab.py      # Extension officer output tab
    ├── evaluation_tab.py           # LLM Evaluation Dashboard tab
    └── styles.py                   # Shared CSS / theme constants
```

---

## Architecture

```
User (Browser)
     │
     ▼
┌─────────────────────────────────────────────────────────┐
│  Streamlit App  (app.py)                                │
│  ┌──────────┐  ┌───────────────┐  ┌──────────────────┐ │
│  │ Home Tab │  │ Recommend Tab │  │ Evaluation Tab   │ │
│  └────┬─────┘  └──────┬────────┘  └──────────────────┘ │
│       │               │                                 │
│  ┌────▼───────────────▼──────────────────────────────┐  │
│  │          Multi-Agent Orchestrator                  │  │
│  │  ┌─────────────────────┐  ┌──────────────────────┐│  │
│  │  │  Pathologist Agent  │→ │ Extension Officer    ││  │
│  │  │  (vision + text)    │  │ Agent  (text)        ││  │
│  │  └─────────────────────┘  └──────────────────────┘│  │
│  └───────────────────────────────────────────────────┘  │
│       │                                                 │
│  ┌────▼──────────────────────────────────────────────┐  │
│  │               Guardrails Layer                     │  │
│  │  Input  ──  Output  ──  Security                   │  │
│  └───────────────────────────────────────────────────┘  │
│       │                                                 │
│  ┌────▼──────────────────────────────────────────────┐  │
│  │           Metrics Tracker (Evaluation)             │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
     │
     ▼
IBM watsonx.ai  →  ibm/granite-vision-3-2-2b
```

---

## Agent Responsibilities

| Agent | Input | Model Call | Output |
|---|---|---|---|
| **Pathologist Agent** | Base64-encoded crop image + optional farmer note | `ibm/granite-vision-3-2-2b` with image + text prompt | Structured diagnosis: disease name, confidence level, symptoms observed, severity |
| **Extension Officer Agent** | Pathologist diagnosis dict | `ibm/granite-vision-3-2-2b` text-only prompt | Safe agricultural recommendations: treatment, prevention, safe chemical use, farmer advisories |
| **Orchestrator** | Raw image file + farmer note | Calls Agent 1 → passes result to Agent 2 → collects metrics | Combined result dict; populates session-state evaluation log |

---

## Required Python Libraries

```
# Core
streamlit>=1.40.0
python-dotenv>=1.0.0

# IBM watsonx.ai
ibm-watsonx-ai>=1.1.0

# Image handling
Pillow>=10.0.0

# Data & display
pandas>=2.0.0
plotly>=5.20.0

# Report generation
(stdlib only — Markdown report uses f-strings)
```

---

## Sub-Tasks

---

### Sub-Task 1 — Project Scaffold and Configuration

**Intent:** Create the directory tree, `requirements.txt`, `.env.example`, and all empty
`__init__.py` files so every subsequent sub-task has a clean import environment to work in.

**Expected Outcomes:**
- `AgriDoctor/` folder contains the full directory structure shown above
- `.env.example` documents every required environment variable
- `requirements.txt` lists all dependencies with minimum versions
- All `__init__.py` files exist (may be empty)

**Todo List:**
1. Create `AgriDoctor/requirements.txt` with all required libraries
2. Create `AgriDoctor/.env.example` with placeholders for `WATSONX_API_KEY`, `WATSONX_PROJECT_ID`, `WATSONX_URL`
3. Create all sub-directories: `agents/`, `guardrails/`, `evaluation/`, `utils/`, `ui/`
4. Create empty `__init__.py` in each sub-directory

**Relevant Context:**
- Workspace root: `c:\EdunetFoundation\Bob Work\AgriDoctor\`
- Existing Streamlit projects (`weather_app/app.py`, `weather_dashboard/app.py`) use
  `st.set_page_config`, `@st.cache_data`, custom CSS via `st.markdown(..., unsafe_allow_html=True)`
  — follow the same patterns
- Existing agent project (`wearable-health-monitor/agents.py`) uses plain Python classes with
  `name` class attribute and a primary action method — follow the same pattern

**Status:** [ ] pending

---

### Sub-Task 2 — IBM watsonx.ai Client Wrapper

**Intent:** Build a single reusable client module that initialises the IBM watsonx.ai connection,
exposes one function for text-only generation and one for vision (image + text) generation.
All agent modules import from here — no direct SDK calls elsewhere.

**Expected Outcomes:**
- `AgriDoctor/utils/watsonx_client.py` is complete
- `get_text_response(prompt, params)` calls `ibm/granite-vision-3-2-2b` text-only
- `get_vision_response(image_b64, prompt, params)` calls the same model with image payload
- Credentials are read from environment variables via `python-dotenv`
- Raises a clear `RuntimeError` if credentials are missing

**Todo List:**
1. Implement `load_credentials()` — reads `.env`, validates required keys
2. Implement `_get_client()` — returns a cached `ModelInference` instance using `ibm-watsonx-ai`
3. Implement `get_text_response(prompt: str, params: dict) -> dict` — returns `{text, tokens_used, latency_ms}`
4. Implement `get_vision_response(image_b64: str, prompt: str, params: dict) -> dict` — same return shape
5. Write module-level docstring explaining usage

**Relevant Context:**
- `ibm-watsonx-ai` SDK: use `ibm_watsonx_ai.foundation_models.ModelInference`
- Model ID: `"ibm/granite-vision-3-2-2b"`
- Auth: `Credentials(api_key=..., url=...)` + `project_id=...`
- Both methods must record wall-clock latency using `time.perf_counter()`
- Return dict must include `tokens_used` (from response metadata) for the evaluation dashboard

**Status:** [ ] pending

---

### Sub-Task 3 — Image Utilities

**Intent:** Provide helper functions for loading, validating, resizing, and base64-encoding crop
images so agent code stays clean of image-processing logic.

**Expected Outcomes:**
- `AgriDoctor/utils/image_utils.py` is complete
- `load_and_validate_image(uploaded_file)` returns a PIL Image or raises on invalid input
- `encode_image_base64(pil_image) -> str` returns a base64 string ready for the watsonx API
- `resize_for_model(pil_image, max_px=1024) -> PIL.Image` resizes while preserving aspect ratio

**Todo List:**
1. Implement `load_and_validate_image` — accepts Streamlit `UploadedFile`, validates MIME type (JPEG/PNG/WEBP only), returns PIL Image
2. Implement `resize_for_model` — downsample so longest edge ≤ `max_px`
3. Implement `encode_image_base64` — convert PIL Image to JPEG bytes → base64 string

**Relevant Context:**
- Streamlit uploaded file exposes `.read()` and `.type` attributes
- Use `Pillow` (`PIL.Image`) for all image operations
- Keep the encoded string under ~1 MB to avoid watsonx request size limits

**Status:** [ ] pending

---

### Sub-Task 4 — Guardrails Layer

**Intent:** Implement three focused guardrail modules that protect the pipeline at input, output,
and security boundaries. Guardrail violations must be logged for the evaluation dashboard.

**Expected Outcomes:**
- `input_guardrails.py` — validates image type, size, and optional text note length
- `output_guardrails.py` — checks LLM responses for minimum length, forbidden content patterns,
  and hallucination markers (e.g. "I don't know", "as an AI")
- `security_guardrails.py` — masks API keys in any string passed to logs/UI, blocks prompt
  injection patterns in user text inputs
- Each module exposes a single `check(...)` function returning `GuardrailResult(passed: bool, reason: str)`

**Todo List:**
1. Define `GuardrailResult` dataclass in `guardrails/__init__.py`
2. Implement `input_guardrails.check_image(uploaded_file) -> GuardrailResult`
   - Reject if file size > 10 MB
   - Reject if MIME type not in `{image/jpeg, image/png, image/webp}`
   - Reject if note text > 500 characters
3. Implement `input_guardrails.check_text(text: str) -> GuardrailResult`
   - Block obvious prompt injection patterns (e.g. "ignore previous instructions")
4. Implement `output_guardrails.check_response(text: str) -> GuardrailResult`
   - Fail if response < 50 characters
   - Fail if response contains refusal markers
   - Warn if response contains uncertainty markers
5. Implement `security_guardrails.mask_secrets(text: str) -> str`
   - Replace anything matching an API key pattern with `[REDACTED]`
6. Implement `security_guardrails.sanitise_user_input(text: str) -> str`
   - Strip HTML tags, strip leading/trailing whitespace

**Relevant Context:**
- `GuardrailResult` will be stored in `st.session_state` by the orchestrator for the evaluation tab
- Prompt injection patterns to detect: `"ignore previous"`, `"disregard"`, `"you are now"`, `"jailbreak"`
- API key pattern regex: `[A-Za-z0-9_\-]{32,}` (conservative, avoids false positives)

**Status:** [ ] pending

---

### Sub-Task 5 — Pathologist Agent

**Intent:** Implement the Pathologist Agent that accepts an encoded crop image and an optional
farmer note, calls the watsonx vision model, and returns a structured diagnosis dictionary.

**Expected Outcomes:**
- `AgriDoctor/agents/pathologist.py` is complete
- `PathologistAgent.analyse(image_b64, farmer_note) -> dict` works end-to-end
- Output dict contains: `disease_name`, `confidence`, `symptoms_observed`, `severity`, `raw_response`, `tokens_used`, `latency_ms`
- Input and output guardrails are applied; violations short-circuit with an error dict
- Agent follows the class-with-`name`-attribute pattern from `wearable-health-monitor/agents.py`

**Todo List:**
1. Define `PathologistAgent` class with `name = "PathologistAgent"`
2. Write a structured vision prompt template that instructs the model to return diagnosis in a
   predictable format (disease name, confidence %, symptoms, severity: mild/moderate/severe)
3. Implement `analyse(image_b64: str, farmer_note: str = "") -> dict`
   - Apply `input_guardrails.check_text(farmer_note)`
   - Call `watsonx_client.get_vision_response(...)`
   - Apply `output_guardrails.check_response(raw_text)`
   - Parse the structured text response into the output dict
   - Return the dict including metrics for the evaluation layer
4. Handle API errors gracefully — return `{error: str}` dict on failure

**Relevant Context:**
- Prompt must instruct model: respond ONLY with structured fields, no extra prose
- Parsing strategy: look for labelled lines (`Disease:`, `Confidence:`, etc.) using simple
  string splitting — no regex required for the initial version
- `farmer_note` is optional context appended to the prompt

**Status:** [ ] pending

---

### Sub-Task 6 — Extension Officer Agent

**Intent:** Implement the Extension Officer Agent that receives the Pathologist's diagnosis and
generates safe, actionable agricultural recommendations using a text-only model call.

**Expected Outcomes:**
- `AgriDoctor/agents/extension_officer.py` is complete
- `ExtensionOfficerAgent.recommend(diagnosis: dict) -> dict` works end-to-end
- Output dict contains: `treatment`, `prevention`, `safe_chemicals`, `farmer_advisory`, `raw_response`, `tokens_used`, `latency_ms`
- Output guardrails are applied
- Agent follows the same class pattern as the Pathologist Agent

**Todo List:**
1. Define `ExtensionOfficerAgent` class with `name = "ExtensionOfficerAgent"`
2. Write a structured text prompt template that takes the diagnosis fields and instructs the model
   to return recommendations in a predictable labelled format
3. Implement `recommend(diagnosis: dict) -> dict`
   - Build prompt from diagnosis dict
   - Call `watsonx_client.get_text_response(...)`
   - Apply `output_guardrails.check_response(raw_text)`
   - Parse labelled lines into the output dict
   - Return dict including metrics
4. Handle error dicts passed from the Pathologist (if `"error"` key present, return early)

**Relevant Context:**
- Prompt must include disease name, severity, and symptoms from the diagnosis dict
- Instruct model to avoid recommending unregistered chemicals and to advise consulting a local
  extension officer for confirmation (responsible AI clause)
- Same parsing approach as the Pathologist Agent (labelled lines)

**Status:** [ ] pending

---

### Sub-Task 7 — Multi-Agent Orchestrator

**Intent:** Implement the orchestrator that sequences Agent 1 → Agent 2, accumulates metrics into
`st.session_state`, and returns the full combined result to the UI layer.

**Expected Outcomes:**
- `AgriDoctor/agents/orchestrator.py` is complete
- `Orchestrator.run(uploaded_file, farmer_note) -> dict` executes the full pipeline
- Session state key `"eval_log"` is a list of per-run metric dicts appended after each run
- Security guardrails are applied before any data leaves the module
- Returns `{diagnosis, recommendations, guardrail_events, run_id, timestamp}`

**Todo List:**
1. Define `Orchestrator` class with `run(uploaded_file, farmer_note) -> dict`
2. Inside `run`:
   a. Apply `security_guardrails.sanitise_user_input(farmer_note)`
   b. Call `image_utils.load_and_validate_image(uploaded_file)`
   c. Apply `input_guardrails.check_image(uploaded_file)` — abort on fail
   d. Call `image_utils.encode_image_base64(pil_image)`
   e. Call `PathologistAgent().analyse(image_b64, farmer_note)`
   f. Call `ExtensionOfficerAgent().recommend(diagnosis)`
   g. Build `guardrail_events` list from all GuardrailResult objects collected
   h. Append metrics entry to `st.session_state["eval_log"]`
   i. Return combined result dict
3. Initialise `st.session_state["eval_log"]` as empty list if not already set

**Relevant Context:**
- `run_id` = `uuid.uuid4().hex[:8]` for lightweight traceability
- `timestamp` = `datetime.now().isoformat()`
- Metrics entry shape: `{run_id, timestamp, agent, latency_ms, tokens_used, guardrail_hits, error}`
- Follow the `run_full_analysis` orchestrator pattern from `wearable-health-monitor/agents.py`

**Status:** [ ] pending

---

### Sub-Task 8 — Metrics Tracker

**Intent:** Implement the metrics tracker that provides the aggregation and formatting functions
consumed by the Evaluation Dashboard tab.

**Expected Outcomes:**
- `AgriDoctor/evaluation/metrics_tracker.py` is complete
- `get_summary_stats(eval_log: list) -> dict` returns aggregated metrics
- `get_agent_table(eval_log: list) -> pd.DataFrame` returns a per-run table for display
- `get_guardrail_summary(eval_log: list) -> dict` counts guardrail hits by type

**Todo List:**
1. Implement `get_summary_stats(eval_log)` — computes:
   - Total runs, total errors, avg latency per agent, total tokens used
2. Implement `get_agent_table(eval_log)` — returns a `pd.DataFrame` with columns:
   `run_id, timestamp, agent, latency_ms, tokens_used, error`
3. Implement `get_guardrail_summary(eval_log)` — counts:
   - Input guardrail blocks, output guardrail blocks, security guardrail hits

**Relevant Context:**
- `eval_log` is `st.session_state["eval_log"]` — a plain Python list of dicts
- Use `pandas` for DataFrame construction only (no DB, no file I/O)

**Status:** [ ] pending

---

### Sub-Task 9 — Report Generator

**Intent:** Implement the Markdown report builder that serialises a completed run result into a
downloadable `.md` file.

**Expected Outcomes:**
- `AgriDoctor/utils/report_generator.py` is complete
- `build_report(result: dict, farmer_note: str) -> str` returns a Markdown string
- Report includes: timestamp, farmer note, diagnosis section, recommendations section, guardrail events

**Todo List:**
1. Implement `build_report(result: dict, farmer_note: str) -> str`
   - Header with app name, run ID, timestamp
   - Farmer note section
   - Pathologist findings section (all diagnosis fields)
   - Extension Officer recommendations section (all recommendation fields)
   - Guardrail events section (list any events)
   - Footer disclaimer (AI-generated, consult a professional)
2. Ensure the function gracefully handles missing or error fields

**Relevant Context:**
- Output is passed directly to `st.download_button(data=..., file_name="agri_doctor_report.md")`
- Use only f-strings and standard `datetime` — no extra dependencies

**Status:** [ ] pending

---

### Sub-Task 10 — Streamlit UI Tabs and app.py

**Intent:** Build all four Streamlit UI components and the main `app.py` entry point that wires
everything together into a polished, themed multi-tab application.

**Expected Outcomes:**
- `app.py` configures the page, applies global CSS, and renders four tabs
- `ui/home_tab.py` — image upload, farmer note input, "Analyse" button, diagnosis display
- `ui/recommendations_tab.py` — renders extension officer output with download button
- `ui/evaluation_tab.py` — LLM Evaluation Dashboard with metrics, charts, guardrail summary
- `ui/styles.py` — shared CSS constants (green agricultural theme)
- Full end-to-end flow works: upload → analyse → see results → download report

**Todo List:**
1. Create `ui/styles.py` with a green-and-earth-tone CSS block (consistent with agricultural theme)
2. Create `ui/home_tab.py`:
   - `st.file_uploader` for crop image (JPEG/PNG/WEBP)
   - `st.text_area` for farmer's note (max 500 chars)
   - "🔬 Analyse Crop" button triggers `Orchestrator().run(...)`
   - Displays diagnosis card: disease name, confidence badge, severity indicator, symptoms
   - Stores result in `st.session_state["last_result"]`
3. Create `ui/recommendations_tab.py`:
   - Reads `st.session_state["last_result"]`
   - Displays four recommendation sections: Treatment, Prevention, Safe Chemicals, Advisory
   - `st.download_button` calls `report_generator.build_report(...)` and offers `.md` download
4. Create `ui/evaluation_tab.py`:
   - Summary metric cards: total runs, avg latency (Pathologist), avg latency (Extension Officer), total tokens, error count
   - `st.dataframe` of per-run log from `metrics_tracker.get_agent_table()`
   - `plotly` bar chart of latency per agent across runs
   - Guardrail event summary table
5. Create `app.py`:
   - `st.set_page_config(page_title="Agri Doctor", page_icon="🌿", layout="wide")`
   - Apply `styles.GLOBAL_CSS`
   - Render tabs: `["🏠 Diagnosis", "💡 Recommendations", "📊 Evaluation", "ℹ️ About"]`
   - About tab: brief app description, model info, disclaimer

**Relevant Context:**
- Follow the `weather_app/app.py` and `weather_dashboard/app.py` CSS card patterns already in the workspace
- Use `st.tabs()` for multi-tab layout (Streamlit native, no routing)
- `st.session_state["last_result"]` is set by home tab; recommendations tab checks for it and shows a prompt if empty
- Plotly chart follows the `go.Figure` + `fig.update_layout` pattern from `weather_dashboard/app.py`

**Status:** [ ] pending

---

## API Integrations

| Service | SDK | Auth Method | Usage |
|---|---|---|---|
| IBM watsonx.ai | `ibm-watsonx-ai` | `WATSONX_API_KEY` + `WATSONX_PROJECT_ID` + `WATSONX_URL` from `.env` | Vision inference (Pathologist), Text inference (Extension Officer) |

**Environment variables required (`.env`):**
```
WATSONX_API_KEY=your_api_key_here
WATSONX_PROJECT_ID=your_project_id_here
WATSONX_URL=https://us-south.ml.cloud.ibm.com
```

---

## Security Implementation

| Layer | Mechanism | Location |
|---|---|---|
| Credential protection | Loaded via `python-dotenv`; never hardcoded or logged | `utils/watsonx_client.py` |
| Secret masking | Regex-based redaction of key-like strings in any logged text | `guardrails/security_guardrails.py` |
| Input sanitisation | Strip HTML, control chars from user text before passing to LLM | `guardrails/security_guardrails.py` |
| Prompt injection detection | Block known injection phrases in farmer note | `guardrails/input_guardrails.py` |
| File upload restriction | MIME type + size limits on images | `guardrails/input_guardrails.py` |
| Response sanitisation | Minimum length + refusal marker checks on LLM output | `guardrails/output_guardrails.py` |
| `.gitignore` | `.env` must be listed to prevent accidental credential commits | Sub-Task 1 |

---

## Testing Strategy

| Test Type | What to Test | Approach |
|---|---|---|
| Guardrail unit tests | Each `check_*` function with valid and invalid inputs | Manual function calls during development; `assert` statements |
| Agent unit tests | Pathologist and Extension Officer with mocked watsonx responses | Use a mock dict instead of live API call; test parsing logic |
| Orchestrator integration | Full pipeline with a sample crop image | Run once with a real `.env` to confirm end-to-end flow |
| UI smoke test | Streamlit app loads without errors | `streamlit run app.py` and verify all tabs render |
| Evaluation dashboard | Metrics correctly aggregated after multiple runs | Run 2–3 analyses and inspect the Evaluation tab |

---

## Deployment Readiness

| Concern | Decision |
|---|---|
| Entry point | `streamlit run AgriDoctor/app.py` |
| Dependencies | Pinned in `AgriDoctor/requirements.txt` |
| Secrets | `.env` file; `.env.example` provided for reference |
| Portability | Pure Python + Streamlit; runs on any machine with Python 3.10+ |
| Streamlit Cloud | Add `AgriDoctor/` as root; set secrets via Streamlit Cloud Secrets (mirrors `.env` vars) |
| IBM Cloud | No change needed — `ibm-watsonx-ai` SDK handles the remote API calls |

---

## Development Phases

| Phase | Sub-Tasks | Description |
|---|---|---|
| **Phase 1 — Foundation** | 1, 2, 3 | Scaffold, watsonx client, image utilities |
| **Phase 2 — Guardrails** | 4 | All three guardrail modules |
| **Phase 3 — Agents** | 5, 6, 7 | Pathologist, Extension Officer, Orchestrator |
| **Phase 4 — Evaluation** | 8, 9 | Metrics tracker, report generator |
| **Phase 5 — UI** | 10 | All Streamlit tabs and app.py |

# 🌿 Agri Doctor

**Agentic AI Crop Disease Diagnosis System**  
Powered by IBM watsonx.ai · IBM Granite Vision · Streamlit

---

## Overview

Agri Doctor is a production-quality **multi-agent AI application** that helps farmers and agricultural extension officers identify crop diseases from photos and generate safe, actionable treatment recommendations — all in real time.

Upload a photo of an affected crop, add an optional note, and the system:

1. **Analyses the image** with a vision-language model to identify the disease, severity, and symptoms
2. **Generates recommendations** for treatment, prevention, safe chemicals, and farmer advisories
3. **Guards every step** with 5 layers of AI safety guardrails
4. **Tracks performance** in a live LLM evaluation dashboard

---

## Screenshots

| Diagnosis Tab | Recommendations Tab | Evaluation Dashboard |
|---|---|---|
| Upload crop image → AI diagnosis with severity badge | Treatment, prevention, safe chemicals, farmer advisory | Latency, tokens, guardrail hits, cost estimates |

---

## Agent Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Multi-Agent Orchestrator            │
│                                                     │
│  ┌─────────────────────┐   ┌─────────────────────┐  │
│  │  Pathologist Agent  │──▶│ Extension Officer   │  │
│  │  (Vision Model)     │   │ Agent (Text Model)  │  │
│  └─────────────────────┘   └─────────────────────┘  │
│           │                          │               │
│    Input Guardrails           Output Guardrails      │
│    Security Guardrails        Agri Safety Guardrails │
│    Agent Communication Guardrails                    │
└─────────────────────────────────────────────────────┘
```

| Agent | Responsibility | Model |
|---|---|---|
| **Pathologist Agent** | Analyses crop images, identifies disease, confidence, severity, and symptoms | `WATSONX_VISION_MODEL` |
| **Extension Officer Agent** | Generates treatment, prevention, safe chemicals, and farmer advisory | `WATSONX_MODEL_ID` |
| **Multi-Agent Orchestrator** | Sequences agents, enforces 12-step guardrail pipeline, records telemetry | — |

---

## Guardrail System (5 Layers)

| Layer | Module | What it checks |
|---|---|---|
| **Input Guardrails** | `guardrails/input_guardrails.py` | Image MIME type, file size, dimensions · Text injection, flooding, homoglyph attacks · PII (email, phone, SSN, credit card) |
| **Output Guardrails** | `guardrails/output_guardrails.py` | Response length, refusal detection, hallucination risk scoring, structured field validation |
| **Security Guardrails** | `guardrails/security_guardrails.py` | Secret masking, HTML sanitisation, rate limiting (50/session, 10/60s), execution budget, payload size |
| **Agent Communication** | `guardrails/agent_communication.py` | Inter-agent message schema, type checking, upstream error propagation, injection guard |
| **Agricultural Safety** | `guardrails/agricultural_safety.py` | 36 WHO Class Ia/Ib + globally banned chemicals, 10 dangerous advice patterns, disclaimer enforcement, severity escalation alerts |

---

## LLM Evaluation Dashboard

The **Evaluation tab** provides real-time visibility into every run:

- ✅ Task completion rate, agent success rates, handoff success
- ⏱️ Response latency — avg and p95 per agent and full pipeline
- 🔤 Token usage per agent per run (stacked bar chart)
- ⚠️ API error rate and breakdown table
- 🛡️ Guardrail intervention rate and per-run hit count
- 🔍 Hallucination risk score per run (pattern-matching signal count)
- 💰 Estimated cost in USD (IBM watsonx.ai output rate × tokens)
- 📋 Full run history table (sortable)

---

## Project Structure

```
AgriDoctor/
├── app.py                          ← Streamlit entry point (4 tabs)
├── .env                            ← Your credentials (never commit)
├── .env.example                    ← Credential template
├── requirements.txt
│
├── agents/
│   ├── pathologist.py              ← Agent 1: vision disease diagnosis
│   ├── extension_officer.py        ← Agent 2: text recommendations
│   └── orchestrator.py             ← 12-step pipeline + dual telemetry
│
├── guardrails/
│   ├── __init__.py                 ← GuardrailResult + GuardrailSeverity
│   ├── input_guardrails.py
│   ├── output_guardrails.py
│   ├── security_guardrails.py
│   ├── agent_communication.py
│   └── agricultural_safety.py
│
├── evaluation/
│   └── metrics_tracker.py          ← KPI computation + series builders
│
├── utils/
│   ├── watsonx_client.py           ← IBM watsonx.ai wrapper (chat API)
│   ├── image_utils.py              ← Load, resize, base64-encode
│   └── report_generator.py         ← Markdown report builder
│
├── ui/
│   ├── styles.py                   ← Global CSS theme
│   ├── home_tab.py                 ← Diagnosis tab
│   ├── recommendations_tab.py      ← Recommendations + download
│   └── evaluation_tab.py           ← LLM & Agent Performance Dashboard
│
├── tests/
│   ├── test_guardrails.py          ← 164 automated guardrail tests
│   └── check_auth.py               ← 7-step authentication diagnostic
│
└── .streamlit/
    ├── config.toml                 ← Theme + upload size config
    └── secrets.toml                ← Streamlit Cloud secrets template
```

---

## Quick Start

### 1. Prerequisites

- Python 3.10 or later
- An [IBM Cloud account](https://cloud.ibm.com) with:
  - An **IBM watsonx.ai** project
  - A **Watson Machine Learning** service instance associated with the project
  - An **IBM Cloud API key** (Manage → Access (IAM) → API keys)

### 2. Clone the repository

```bash
git clone https://github.com/your-username/agri-doctor.git
cd agri-doctor/AgriDoctor
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure credentials

Create `AgriDoctor/.env` (copy from the template):

```bash
cp .env.example .env
```

Edit `.env` and fill in your values:

```env
WATSONX_API_KEY=your_ibm_cloud_api_key
WATSONX_PROJECT_ID=your_watsonx_project_id
WATSONX_URL=https://us-south.ml.cloud.ibm.com

# Optional: override model IDs
WATSONX_VISION_MODEL=mistralai/mistral-small-3-1-24b-instruct-2503
WATSONX_MODEL_ID=ibm/granite-4-h-small
```

> **Never commit `.env` to version control.** It is listed in `.gitignore`.

### 5. Verify authentication

```bash
python tests/check_auth.py
```

All 7 steps should show `OK`. If Step 7 fails with `no_associated_service_instance_error`, follow the fix instructions printed by the script.

### 6. Run the application

```bash
cd AgriDoctor
python -m streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

---

## Running Tests

```bash
cd AgriDoctor
python tests/test_guardrails.py
```

Expected output: `RESULTS: 164/164 passed | 0 failed`

---

## IBM watsonx.ai Setup Guide

### Step 1 — Create an API key

1. Log in to [https://cloud.ibm.com](https://cloud.ibm.com)
2. Go to **Manage → Access (IAM) → API keys**
3. Click **Create** → give it a name → **Copy** the key immediately (shown once)
4. Paste it as `WATSONX_API_KEY` in your `.env`

### Step 2 — Create or find your watsonx.ai project

1. Go to [https://dataplatform.cloud.ibm.com/wx/home](https://dataplatform.cloud.ibm.com/wx/home)
2. Open or create a project
3. Go to **Manage → General** and copy the **Project ID**
4. Paste it as `WATSONX_PROJECT_ID` in your `.env`

### Step 3 — Associate a Watson Machine Learning instance

1. Inside your project, go to **Manage → Services & integrations**
2. Click **Associate service**
3. Select or provision a **Watson Machine Learning** instance
4. Click **Associate**

> This step is required. Without it, inference calls return HTTP 403 (`no_associated_service_instance_error`).

---

## Deployment to Streamlit Cloud

1. Push the repository to GitHub (ensure `.env` is in `.gitignore`)
2. Go to [share.streamlit.io](https://share.streamlit.io) and connect your repo
3. Set the **Main file path** to `AgriDoctor/app.py`
4. Go to **Settings → Secrets** and add:

```toml
WATSONX_API_KEY     = "your_api_key"
WATSONX_PROJECT_ID  = "your_project_id"
WATSONX_URL         = "https://us-south.ml.cloud.ibm.com"
WATSONX_VISION_MODEL = "mistralai/mistral-small-3-1-24b-instruct-2503"
WATSONX_MODEL_ID     = "ibm/granite-4-h-small"
```

---

## Technical Stack

| Component | Technology |
|---|---|
| UI framework | Streamlit 1.64 |
| Vision LLM | IBM watsonx.ai — configurable via `WATSONX_VISION_MODEL` |
| Text LLM | IBM watsonx.ai — configurable via `WATSONX_MODEL_ID` |
| IBM SDK | `ibm-watsonx-ai` ≥ 1.1.0 |
| Image processing | Pillow ≥ 10.0 |
| Data & charts | pandas ≥ 2.0, plotly ≥ 5.20 |
| Credentials | python-dotenv ≥ 1.0 |
| Python | 3.10+ |

---

## Disclaimer

Agri Doctor is an **AI-assisted decision support tool** only.

- Results are generated by AI models and may not be 100% accurate.
- Always verify recommendations with a qualified agricultural extension officer or plant pathologist.
- Do not apply chemical treatments solely based on AI output.
- Registered chemical use must comply with local agricultural regulations.

---

## License

This project is released for educational and research use.  
IBM Granite and watsonx.ai are trademarks of IBM Corporation.  
Third-party models (e.g. Mistral) are governed by their own licences.

---

*Built with ❤️ using IBM watsonx.ai · IBM Granite · Streamlit*

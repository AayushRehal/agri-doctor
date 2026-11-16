"""
evaluation/metrics_tracker.py
==============================
Full KPI computation for the Agri Doctor LLM & Agent Performance Dashboard.

Consumes two session-state lists populated by the Orchestrator:
  st.session_state["run_log"]   — one record per complete pipeline run
  st.session_state["eval_log"]  — one record per agent call within a run

Data sources and what can / cannot be measured
───────────────────────────────────────────────
MEASURED from live telemetry
  • Task completion rate         (run_log: completed runs / total runs)
  • Agent execution success      (run_log: path/ext error flags)
  • Agent handoff success        (run_log: handoff_success flag)
  • Response latency             (run_log: path_latency_ms, ext_latency_ms, pipeline_ms)
  • Token usage                  (run_log: path_tokens, ext_tokens)
  • API error rate               (run_log: path_error + ext_error / total agent calls)
  • Guardrail intervention rate  (run_log: guardrail_hits / total runs)
  • Hallucination risk score     (run_log: hallucination_score from output guardrail)
  • Cost estimate                (token counts × published per-token pricing for
                                  ibm/granite-vision-3-2-2b on IBM watsonx.ai)

NOT AVAILABLE — explicitly surfaced as such in the UI
  • Ground-truth accuracy        (no labelled crop disease dataset in-session)
  • BLEU / ROUGE / BERTScore     (no reference texts available at inference time)
  • Human-rater scores           (no human feedback loop implemented)

Public API
──────────
  compute_kpis(run_log, eval_log)        -> dict
  get_run_table(run_log)                 -> pd.DataFrame
  get_latency_series(run_log)            -> dict
  get_token_series(run_log)              -> dict
  get_guardrail_detail(run_log)          -> dict
  get_error_breakdown(run_log)           -> dict
  get_hallucination_series(run_log)      -> dict
  estimate_cost(run_log)                 -> dict
"""

import pandas as pd
from datetime import datetime

# ── Pricing constants ─────────────────────────────────────────────────────────
# IBM watsonx.ai published pricing for ibm/granite-vision-3-2-2b
# Source: https://www.ibm.com/products/watsonx-ai/foundation-models
# Rates are in USD per 1 000 tokens (as of the last known pricing update).
# These are approximations; always verify against current IBM Cloud pricing.
_INPUT_PRICE_PER_1K  = 0.000375   # USD per 1 000 input tokens
_OUTPUT_PRICE_PER_1K = 0.001125   # USD per 1 000 output tokens
# The SDK returns total (input + output) tokens; we cannot split them here.
# We use the output rate as a conservative single rate.
_TOKENS_PER_1K       = 1_000


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    return round(numerator / denominator, 4) if denominator else default


def _pct(part: float, total: float) -> float:
    return round(100.0 * _safe_div(part, total), 1)


def _avg(values: list) -> float:
    vals = [v for v in values if v is not None and v > 0]
    return round(sum(vals) / len(vals), 1) if vals else 0.0


def _p95(values: list) -> float:
    """Return the 95th-percentile of a list of floats."""
    vals = sorted(v for v in values if v is not None and v > 0)
    if not vals:
        return 0.0
    idx = max(0, int(len(vals) * 0.95) - 1)
    return round(vals[idx], 1)


# ── KPI computation ───────────────────────────────────────────────────────────

def compute_kpis(run_log: list, eval_log: list) -> dict:
    """
    Compute all measurable KPIs from the two telemetry lists.

    Returns a dict with the following top-level keys:
      pipeline, agents, latency, tokens, errors, guardrails,
      hallucination, cost, unavailable
    """
    if not run_log:
        return _empty_kpis()

    total_runs      = len(run_log)
    completed       = [r for r in run_log if not r.get("aborted")]
    aborted         = [r for r in run_log if r.get("aborted")]
    n_completed     = len(completed)

    # ── Pipeline KPIs ──────────────────────────────────────────────────────
    task_completion_rate = _pct(n_completed, total_runs)

    # ── Agent execution KPIs ───────────────────────────────────────────────
    path_calls   = [r for r in completed]        # one Pathologist call per completed run
    ext_calls    = [r for r in completed]        # one Extension Officer call per completed run
    path_success = sum(1 for r in path_calls if not r["path_error"])
    ext_success  = sum(1 for r in ext_calls  if not r["ext_error"])
    path_success_rate = _pct(path_success, len(path_calls))
    ext_success_rate  = _pct(ext_success,  len(ext_calls))

    # ── Agent handoff KPIs ─────────────────────────────────────────────────
    handoff_successes   = sum(1 for r in completed if r.get("handoff_success"))
    handoff_success_rate = _pct(handoff_successes, n_completed)

    # ── Latency KPIs ────────────────────────────────────────────────────────
    path_latencies   = [r["path_latency_ms"] for r in completed]
    ext_latencies    = [r["ext_latency_ms"]  for r in completed]
    pipe_latencies   = [r["pipeline_ms"]     for r in completed]

    # ── Token KPIs ──────────────────────────────────────────────────────────
    path_tokens_list = [r["path_tokens"] for r in completed]
    ext_tokens_list  = [r["ext_tokens"]  for r in completed]
    total_path_tok   = sum(path_tokens_list)
    total_ext_tok    = sum(ext_tokens_list)
    total_tokens     = total_path_tok + total_ext_tok

    # ── Error KPIs ───────────────────────────────────────────────────────────
    # Total agent invocations (2 per completed run)
    total_agent_calls = n_completed * 2
    total_api_errors  = (sum(1 for r in completed if r["path_error"]) +
                         sum(1 for r in completed if r["ext_error"]))
    api_error_rate    = _pct(total_api_errors, max(total_agent_calls, 1))

    # ── Guardrail KPIs ───────────────────────────────────────────────────────
    total_guardrail_hits   = sum(r["guardrail_hits"] for r in run_log)
    runs_with_guardrails   = sum(1 for r in run_log if r["guardrail_hits"] > 0)
    guardrail_rate         = _pct(runs_with_guardrails, total_runs)

    # ── Hallucination risk KPIs ──────────────────────────────────────────────
    # Measured: output-guardrail hallucination_score (0–N signal count)
    # This is a risk INDICATOR, not a ground-truth accuracy measurement.
    hall_scores  = [r["hallucination_score"] for r in completed]
    hall_nonzero = sum(1 for s in hall_scores if s > 0)
    hall_flagged_rate = _pct(hall_nonzero, n_completed)

    # ── Cost estimate ────────────────────────────────────────────────────────
    # Uses published watsonx.ai pricing. SDK returns completion tokens only;
    # input tokens are not separately reported by the current SDK version.
    # We apply the output rate uniformly and label it as an estimate.
    cost_path = round(total_path_tok * _OUTPUT_PRICE_PER_1K / _TOKENS_PER_1K, 6)
    cost_ext  = round(total_ext_tok  * _OUTPUT_PRICE_PER_1K / _TOKENS_PER_1K, 6)
    cost_total = round(cost_path + cost_ext, 6)

    return {
        "pipeline": {
            "total_runs":           total_runs,
            "completed_runs":       n_completed,
            "aborted_runs":         len(aborted),
            "task_completion_rate": task_completion_rate,   # %
        },
        "agents": {
            "path_success_rate":    path_success_rate,      # %
            "ext_success_rate":     ext_success_rate,       # %
            "handoff_success_rate": handoff_success_rate,   # %
        },
        "latency": {
            "path_avg_ms":          _avg(path_latencies),
            "path_p95_ms":          _p95(path_latencies),
            "ext_avg_ms":           _avg(ext_latencies),
            "ext_p95_ms":           _p95(ext_latencies),
            "pipeline_avg_ms":      _avg(pipe_latencies),
            "pipeline_p95_ms":      _p95(pipe_latencies),
        },
        "tokens": {
            "total":                total_tokens,
            "path_total":           total_path_tok,
            "ext_total":            total_ext_tok,
            "path_avg":             round(_avg(path_tokens_list)),
            "ext_avg":              round(_avg(ext_tokens_list)),
        },
        "errors": {
            "api_error_rate":       api_error_rate,         # %
            "total_api_errors":     total_api_errors,
            "total_agent_calls":    total_agent_calls,
        },
        "guardrails": {
            "total_hits":           total_guardrail_hits,
            "runs_with_hits":       runs_with_guardrails,
            "guardrail_rate":       guardrail_rate,         # %
        },
        "hallucination": {
            "flagged_rate":         hall_flagged_rate,      # %
            "flagged_count":        hall_nonzero,
            "total_checked":        n_completed,
            "note":                 "Risk indicator only — not ground-truth accuracy",
        },
        "cost": {
            "total_usd":            cost_total,
            "path_usd":             cost_path,
            "ext_usd":              cost_ext,
            "tokens_priced":        total_tokens,
            "rate_per_1k_usd":      _OUTPUT_PRICE_PER_1K,
            "note":                 (
                "Estimate using ibm/granite-vision-3-2-2b output rate "
                f"(${_OUTPUT_PRICE_PER_1K}/1K tokens). "
                "SDK currently returns completion tokens only; actual cost may differ."
            ),
        },
        "unavailable": [
            {
                "metric": "Ground-truth Accuracy",
                "reason": "No labelled crop-disease reference dataset available in-session.",
            },
            {
                "metric": "BLEU / ROUGE / BERTScore",
                "reason": "No reference texts available at inference time.",
            },
            {
                "metric": "Human-Rater Score",
                "reason": "No human feedback loop is implemented.",
            },
            {
                "metric": "Per-call Input Token Count",
                "reason": (
                    "The ibm-watsonx-ai SDK's generate_text() returns completion "
                    "tokens only; input token count is not separately reported."
                ),
            },
        ],
    }


def _empty_kpis() -> dict:
    return {
        "pipeline":     {"total_runs": 0, "completed_runs": 0, "aborted_runs": 0,
                         "task_completion_rate": 0.0},
        "agents":       {"path_success_rate": 0.0, "ext_success_rate": 0.0,
                         "handoff_success_rate": 0.0},
        "latency":      {"path_avg_ms": 0.0, "path_p95_ms": 0.0,
                         "ext_avg_ms": 0.0,  "ext_p95_ms": 0.0,
                         "pipeline_avg_ms": 0.0, "pipeline_p95_ms": 0.0},
        "tokens":       {"total": 0, "path_total": 0, "ext_total": 0,
                         "path_avg": 0, "ext_avg": 0},
        "errors":       {"api_error_rate": 0.0, "total_api_errors": 0,
                         "total_agent_calls": 0},
        "guardrails":   {"total_hits": 0, "runs_with_hits": 0, "guardrail_rate": 0.0},
        "hallucination":{"flagged_rate": 0.0, "flagged_count": 0, "total_checked": 0,
                         "note": "Risk indicator only — not ground-truth accuracy"},
        "cost":         {"total_usd": 0.0, "path_usd": 0.0, "ext_usd": 0.0,
                         "tokens_priced": 0, "rate_per_1k_usd": _OUTPUT_PRICE_PER_1K,
                         "note": "Estimate using completion tokens × output rate."},
        "unavailable":  [],
    }


# ── Table builders ────────────────────────────────────────────────────────────

def get_run_table(run_log: list) -> pd.DataFrame:
    """
    Build a human-readable per-run DataFrame for the history table.

    Columns: Run, Timestamp, Status, Pathologist, Ext Officer,
             Pipeline (ms), Tokens, Guardrail Hits, Disease, Severity
    """
    if not run_log:
        return pd.DataFrame(columns=[
            "Run", "Timestamp", "Status", "Pathologist",
            "Ext Officer", "Pipeline (ms)", "Tokens",
            "Guardrail Hits", "Disease", "Severity",
        ])

    rows = []
    for i, r in enumerate(run_log, 1):
        if r.get("aborted"):
            status = "Aborted"
            path_s = "—"
            ext_s  = "—"
        else:
            status = "Complete"
            path_s = "Error" if r["path_error"] else "OK"
            ext_s  = "Error" if r["ext_error"]  else "OK"

        rows.append({
            "Run":           i,
            "Timestamp":     r["timestamp"][:19].replace("T", " "),
            "Status":        status,
            "Pathologist":   path_s,
            "Ext Officer":   ext_s,
            "Pipeline (ms)": r["pipeline_ms"],
            "Tokens":        r["path_tokens"] + r["ext_tokens"],
            "Guardrail Hits":r["guardrail_hits"],
            "Disease":       r.get("disease", ""),
            "Severity":      r.get("severity", ""),
        })

    return pd.DataFrame(rows)


def get_latency_series(run_log: list) -> dict:
    """
    Return per-run latency series for charting.
    Keys: labels, path_ms, ext_ms, pipeline_ms
    """
    completed = [r for r in run_log if not r.get("aborted")]
    labels     = [f"Run {i+1}" for i, r in enumerate(run_log)
                  if not r.get("aborted")]
    return {
        "labels":      labels,
        "path_ms":     [r["path_latency_ms"] for r in completed],
        "ext_ms":      [r["ext_latency_ms"]  for r in completed],
        "pipeline_ms": [r["pipeline_ms"]     for r in completed],
    }


def get_token_series(run_log: list) -> dict:
    """
    Return per-run token series for charting.
    Keys: labels, path_tokens, ext_tokens
    """
    completed = [r for r in run_log if not r.get("aborted")]
    labels    = [f"Run {i+1}" for i, r in enumerate(run_log)
                 if not r.get("aborted")]
    return {
        "labels":      labels,
        "path_tokens": [r["path_tokens"] for r in completed],
        "ext_tokens":  [r["ext_tokens"]  for r in completed],
    }


def get_guardrail_detail(run_log: list) -> dict:
    """
    Summarise guardrail events across all runs.
    Returns counts by run status (aborted vs completed) and total hits.
    """
    total_hits   = sum(r["guardrail_hits"] for r in run_log)
    aborted_hits = sum(r["guardrail_hits"] for r in run_log if r.get("aborted"))
    runtime_hits = total_hits - aborted_hits

    return {
        "total_hits":   total_hits,
        "aborted_hits": aborted_hits,   # input/security blocks that stopped the pipeline
        "runtime_hits": runtime_hits,   # output/agent-level hits on completed runs
    }


def get_error_breakdown(run_log: list) -> dict:
    """
    Break down errors by type across runs.
    """
    completed = [r for r in run_log if not r.get("aborted")]
    return {
        "aborted":       sum(1 for r in run_log if r.get("aborted")),
        "path_errors":   sum(1 for r in completed if r["path_error"]),
        "ext_errors":    sum(1 for r in completed if r["ext_error"]),
        "both_errors":   sum(1 for r in completed if r["path_error"] and r["ext_error"]),
        "clean_runs":    sum(1 for r in completed
                             if not r["path_error"] and not r["ext_error"]),
    }


def get_hallucination_series(run_log: list) -> dict:
    """
    Return per-run hallucination risk score series.
    Score = count of risk signal patterns matched in the LLM response.
    """
    completed = [r for r in run_log if not r.get("aborted")]
    labels    = [f"Run {i+1}" for i, r in enumerate(run_log)
                 if not r.get("aborted")]
    return {
        "labels": labels,
        "scores": [r["hallucination_score"] for r in completed],
    }


def estimate_cost(run_log: list) -> dict:
    """
    Re-compute cost breakdown from the run log.
    Returns the same structure as kpis["cost"] for standalone use.
    """
    completed  = [r for r in run_log if not r.get("aborted")]
    path_toks  = sum(r["path_tokens"] for r in completed)
    ext_toks   = sum(r["ext_tokens"]  for r in completed)
    total_toks = path_toks + ext_toks
    return {
        "total_usd":       round((total_toks * _OUTPUT_PRICE_PER_1K) / _TOKENS_PER_1K, 6),
        "path_usd":        round((path_toks  * _OUTPUT_PRICE_PER_1K) / _TOKENS_PER_1K, 6),
        "ext_usd":         round((ext_toks   * _OUTPUT_PRICE_PER_1K) / _TOKENS_PER_1K, 6),
        "tokens_priced":   total_toks,
        "rate_per_1k_usd": _OUTPUT_PRICE_PER_1K,
    }


# ── Backward-compatible wrappers for existing callers ─────────────────────────

def get_summary_stats(eval_log: list) -> dict:
    """Legacy function — keep existing evaluation_tab callers working."""
    if not eval_log:
        return {
            "total_runs": 0, "total_errors": 0, "total_tokens": 0,
            "avg_latency_pathologist_ms": 0.0, "avg_latency_extension_ms": 0.0,
            "guardrail_hits_total": 0,
        }
    run_ids  = {e["run_id"] for e in eval_log}
    path_e   = [e for e in eval_log if e["agent"] == "PathologistAgent"]
    ext_e    = [e for e in eval_log if e["agent"] == "ExtensionOfficerAgent"]
    all_e    = [e for e in eval_log if e["agent"] != "input_guardrail"]
    return {
        "total_runs":                 len(run_ids),
        "total_errors":               sum(1 for e in all_e if e["error"]),
        "total_tokens":               sum(e["tokens_used"] for e in eval_log),
        "avg_latency_pathologist_ms": _avg([e["latency_ms"] for e in path_e]),
        "avg_latency_extension_ms":   _avg([e["latency_ms"] for e in ext_e]),
        "guardrail_hits_total":       sum(e["guardrail_hits"] for e in eval_log),
    }


def get_agent_table(eval_log: list) -> pd.DataFrame:
    """Legacy function — keep existing evaluation_tab callers working."""
    if not eval_log:
        return pd.DataFrame(columns=[
            "Run ID", "Timestamp", "Agent", "Latency (ms)", "Tokens Used", "Error"
        ])
    rows = [{
        "Run ID":       e.get("run_id", ""),
        "Timestamp":    e.get("timestamp", "")[:19].replace("T", " "),
        "Agent":        e.get("agent", ""),
        "Latency (ms)": e.get("latency_ms", 0),
        "Tokens Used":  e.get("tokens_used", 0),
        "Error":        "Yes" if e.get("error") else "No",
    } for e in eval_log]
    return pd.DataFrame(rows)


def get_guardrail_summary(eval_log: list) -> dict:
    """Legacy function — keep existing evaluation_tab callers working."""
    input_b  = sum(1 for e in eval_log if e["agent"] == "input_guardrail"
                   and e["guardrail_hits"] > 0)
    output_b = sum(1 for e in eval_log
                   if e["agent"] in ("PathologistAgent", "ExtensionOfficerAgent")
                   and e["guardrail_hits"] > 0)
    total    = sum(e["guardrail_hits"] for e in eval_log)
    return {
        "input_blocks":  input_b,
        "output_blocks": output_b,
        "security_hits": max(0, total - input_b - output_b),
        "total":         total,
    }

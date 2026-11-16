"""
ui/evaluation_tab.py
====================
Agri Doctor — LLM & Agent Performance Dashboard

Sections
────────
1.  Header and data-source notice
2.  Top KPI row (9 measured cards)
3.  Pipeline & Agent Reliability (task completion, handoff, success rates)
4.  Response Latency (line chart avg/p95 + per-run grouped bars)
5.  Token Usage (stacked bar per run + summary)
6.  API Error Rate (donut + per-run error table)
7.  Guardrail Intervention Rate (bar chart + breakdown)
8.  Hallucination Risk (line chart + explanation of method)
9.  Cost Tracking (estimated USD + per-agent breakdown + disclosure)
10. Run History table (all runs, sortable)
11. Unavailable Metrics (clearly labelled, with reasons)
12. Clear session button
"""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

from evaluation.metrics_tracker import (
    compute_kpis,
    get_run_table,
    get_latency_series,
    get_token_series,
    get_guardrail_detail,
    get_error_breakdown,
    get_hallucination_series,
)
from ui.styles import metric_card_html


# ── Colour palette (matches app theme) ────────────────────────────────────────
_C_PATH   = "#2d5a27"   # dark green  — Pathologist Agent
_C_EXT    = "#6aaa5e"   # light green — Extension Officer Agent
_C_PIPE   = "#b8dba8"   # very light  — Pipeline total
_C_ERR    = "#c0392b"   # red         — errors
_C_WARN   = "#e67e22"   # amber       — warnings / hallucination risk
_C_OK     = "#27ae60"   # bright green — OK / pass
_C_GRID   = "#e0ecd8"
_C_BG     = "#f4f7f0"
_C_PLOT   = "white"

_LAYOUT_BASE = dict(
    paper_bgcolor=_C_BG,
    plot_bgcolor=_C_PLOT,
    font=dict(color="#3d4f38", size=12),
    margin=dict(l=40, r=20, t=40, b=40),
    hovermode="x unified",
)


def _layout(**kwargs):
    d = _LAYOUT_BASE.copy()
    d.update(kwargs)
    return d


# ── Helpers ────────────────────────────────────────────────────────────────────

def _rate_color(rate: float, good_above: float = 90.0) -> str:
    """Return CSS color for a rate metric."""
    if rate >= good_above:
        return _C_OK
    if rate >= 70:
        return _C_WARN
    return _C_ERR


def _kpi_card(icon: str, label: str, value: str,
              sub: str = "", color: str = "#2d5a27") -> str:
    """Extended metric card with optional sub-text and custom value colour."""
    sub_html = f'<div style="font-size:0.72rem;color:#57606a;margin-top:3px;">{sub}</div>' if sub else ""
    return (
        f'<div class="metric-card">'
        f'<div class="card-icon">{icon}</div>'
        f'<div class="card-label">{label}</div>'
        f'<div class="card-value" style="color:{color};">{value}</div>'
        f'{sub_html}'
        f'</div>'
    )


def _notice(text: str):
    st.markdown(
        f'<div style="background:#fef9e7;border:1px solid #f9d342;border-radius:8px;'
        f'padding:10px 14px;font-size:0.82rem;color:#7d6608;margin-bottom:12px;">'
        f'ℹ️ {text}</div>',
        unsafe_allow_html=True,
    )


def _unavailable_badge(metric: str, reason: str):
    st.markdown(
        f'<div style="background:#f7f8fa;border:1px solid #e5e7eb;border-radius:8px;'
        f'padding:10px 14px;margin-bottom:8px;">'
        f'<strong style="color:#57606a;">⛔ {metric}</strong>'
        f'<span style="color:#57606a;font-size:0.82rem;"> — {reason}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ── Main render ────────────────────────────────────────────────────────────────

def render():
    """Render the full LLM & Agent Performance Dashboard."""

    st.markdown("### 📊 LLM & Agent Performance Dashboard")
    st.markdown(
        "All metrics are derived from live application telemetry collected during "
        "this session. Metrics that cannot be measured without ground-truth labels "
        "or external tools are listed separately at the bottom."
    )

    run_log  = st.session_state.get("run_log",  [])
    eval_log = st.session_state.get("eval_log", [])

    if not run_log:
        st.info(
            "💡 No data yet. Run at least one crop analysis in the **Diagnosis** tab "
            "to populate the dashboard."
        )
        return

    kpis = compute_kpis(run_log, eval_log)

    # ════════════════════════════════════════════════════════════════════════
    # Section 1 — Top KPI Row
    # ════════════════════════════════════════════════════════════════════════
    st.markdown("#### 🏆 Key Performance Indicators")

    p = kpis["pipeline"]
    a = kpis["agents"]
    l = kpis["latency"]
    t = kpis["tokens"]
    e = kpis["errors"]
    g = kpis["guardrails"]
    h = kpis["hallucination"]
    c = kpis["cost"]

    cols = st.columns(9)
    kpi_cards = [
        (cols[0], "✅", "Task Completion",
         f"{p['task_completion_rate']}%",
         f"{p['completed_runs']}/{p['total_runs']} runs",
         _rate_color(p["task_completion_rate"])),

        (cols[1], "🤖", "Path. Success",
         f"{a['path_success_rate']}%",
         "Pathologist Agent",
         _rate_color(a["path_success_rate"])),

        (cols[2], "🤝", "Handoff Success",
         f"{a['handoff_success_rate']}%",
         "Agent-to-agent",
         _rate_color(a["handoff_success_rate"])),

        (cols[3], "⏱️", "Avg Latency",
         f"{l['path_avg_ms']:,.0f} ms",
         "Pathologist p95: " + f"{l['path_p95_ms']:,.0f} ms",
         "#2d5a27"),

        (cols[4], "🔤", "Total Tokens",
         f"{t['total']:,}",
         f"Avg {t['path_avg']+t['ext_avg']}/run",
         "#2d5a27"),

        (cols[5], "⚠️", "API Error Rate",
         f"{e['api_error_rate']}%",
         f"{e['total_api_errors']} errors",
         _rate_color(100 - e["api_error_rate"])),

        (cols[6], "🛡️", "Guardrail Rate",
         f"{g['guardrail_rate']}%",
         f"{g['total_hits']} total hits",
         _rate_color(100 - g["guardrail_rate"])),

        (cols[7], "🔍", "Halluc. Flagged",
         f"{h['flagged_rate']}%",
         f"{h['flagged_count']} runs",
         _rate_color(100 - h["flagged_rate"], good_above=5)),

        (cols[8], "💰", "Est. Cost",
         f"${c['total_usd']:.4f}",
         "USD this session",
         "#2d5a27"),
    ]
    for col, icon, label, value, sub, color in kpi_cards:
        with col:
            st.markdown(_kpi_card(icon, label, value, sub, color),
                        unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("---")

    # ════════════════════════════════════════════════════════════════════════
    # Section 2 — Pipeline & Agent Reliability
    # ════════════════════════════════════════════════════════════════════════
    st.markdown("#### 🤖 Pipeline & Agent Reliability")

    r1, r2 = st.columns(2, gap="large")

    with r1:
        # Success rate gauge-style bar chart
        metrics = {
            "Task Completion":    p["task_completion_rate"],
            "Pathologist Success": a["path_success_rate"],
            "Ext Officer Success": a["ext_success_rate"],
            "Handoff Success":    a["handoff_success_rate"],
        }
        fig_rel = go.Figure(go.Bar(
            x=list(metrics.values()),
            y=list(metrics.keys()),
            orientation="h",
            marker_color=[_rate_color(v) for v in metrics.values()],
            text=[f"{v:.1f}%" for v in metrics.values()],
            textposition="inside",
        ))
        fig_rel.update_layout(
            **_layout(title="Success Rates (%)"),
            xaxis=dict(range=[0, 100], title="", gridcolor=_C_GRID),
            yaxis=dict(title="", showgrid=False),
        )
        st.plotly_chart(fig_rel, use_container_width=True)

    with r2:
        # Pie — run outcomes
        err = get_error_breakdown(run_log)
        labels_pie = ["Clean Runs", "Pathologist Error",
                      "Ext Officer Error", "Aborted"]
        values_pie = [err["clean_runs"], err["path_errors"],
                      err["ext_errors"],  err["aborted"]]
        values_pie = [max(v, 0) for v in values_pie]

        fig_pie = go.Figure(go.Pie(
            labels=labels_pie,
            values=values_pie,
            marker_colors=[_C_OK, _C_ERR, _C_WARN, "#95a5a6"],
            hole=0.45,
            textinfo="label+percent",
            textfont_size=11,
        ))
        fig_pie.update_layout(
            **_layout(title="Run Outcome Distribution"),
            showlegend=False,
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    st.markdown("---")

    # ════════════════════════════════════════════════════════════════════════
    # Section 3 — Response Latency
    # ════════════════════════════════════════════════════════════════════════
    st.markdown("#### ⏱️ Response Latency")

    lat_cols = st.columns(3)
    lat_meta = [
        ("Pathologist Agent", l["path_avg_ms"], l["path_p95_ms"]),
        ("Extension Officer", l["ext_avg_ms"],  l["ext_p95_ms"]),
        ("Full Pipeline",     l["pipeline_avg_ms"], l["pipeline_p95_ms"]),
    ]
    for col, (label, avg, p95) in zip(lat_cols, lat_meta):
        with col:
            st.markdown(
                _kpi_card("⏱️", label, f"{avg:,.0f} ms",
                          sub=f"p95: {p95:,.0f} ms"),
                unsafe_allow_html=True,
            )

    st.markdown("<br>", unsafe_allow_html=True)

    series = get_latency_series(run_log)
    if series["labels"]:
        fig_lat = go.Figure()
        fig_lat.add_trace(go.Scatter(
            x=series["labels"], y=series["path_ms"],
            name="Pathologist Agent", mode="lines+markers",
            line=dict(color=_C_PATH, width=2),
            marker=dict(size=6),
        ))
        fig_lat.add_trace(go.Scatter(
            x=series["labels"], y=series["ext_ms"],
            name="Extension Officer", mode="lines+markers",
            line=dict(color=_C_EXT, width=2),
            marker=dict(size=6),
        ))
        fig_lat.add_trace(go.Scatter(
            x=series["labels"], y=series["pipeline_ms"],
            name="Full Pipeline", mode="lines+markers",
            line=dict(color=_C_PIPE, width=2, dash="dot"),
            marker=dict(size=6),
        ))
        fig_lat.update_layout(
            **_layout(title="Latency per Run (ms)"),
            xaxis=dict(title="", showgrid=False),
            yaxis=dict(title="ms", gridcolor=_C_GRID),
            legend=dict(orientation="h", yanchor="bottom", y=1.02,
                        xanchor="right", x=1),
        )
        st.plotly_chart(fig_lat, use_container_width=True)

    st.markdown("---")

    # ════════════════════════════════════════════════════════════════════════
    # Section 4 — Token Usage
    # ════════════════════════════════════════════════════════════════════════
    st.markdown("#### 🔤 Token Usage")

    tok_cols = st.columns(4)
    tok_meta = [
        ("Total Tokens",        f"{t['total']:,}",     "all agents, all runs", "🔤"),
        ("Pathologist Tokens",  f"{t['path_total']:,}", f"avg {t['path_avg']}/run", "🔬"),
        ("Ext Officer Tokens",  f"{t['ext_total']:,}",  f"avg {t['ext_avg']}/run",  "💡"),
    ]
    for col, (label, val, sub, icon) in zip(tok_cols[:3], tok_meta):
        with col:
            st.markdown(_kpi_card(icon, label, val, sub),
                        unsafe_allow_html=True)
    with tok_cols[3]:
        total_runs_shown = p["completed_runs"] or 1
        avg_total = round((t["path_avg"] + t["ext_avg"]))
        st.markdown(_kpi_card("📈", "Avg Tokens/Run", f"{avg_total:,}",
                              sub="Pathologist + Extension"),
                    unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    tok_series = get_token_series(run_log)
    if tok_series["labels"]:
        fig_tok = go.Figure()
        fig_tok.add_trace(go.Bar(
            x=tok_series["labels"], y=tok_series["path_tokens"],
            name="Pathologist Agent", marker_color=_C_PATH,
        ))
        fig_tok.add_trace(go.Bar(
            x=tok_series["labels"], y=tok_series["ext_tokens"],
            name="Extension Officer", marker_color=_C_EXT,
        ))
        fig_tok.update_layout(
            **_layout(title="Token Usage per Run"),
            barmode="stack",
            xaxis=dict(title="", showgrid=False),
            yaxis=dict(title="Tokens", gridcolor=_C_GRID),
            legend=dict(orientation="h", yanchor="bottom", y=1.02,
                        xanchor="right", x=1),
        )
        st.plotly_chart(fig_tok, use_container_width=True)

    _notice(
        "Token counts reflect completion tokens reported by the ibm-watsonx-ai SDK. "
        "Input token counts are not separately available from this SDK version."
    )

    st.markdown("---")

    # ════════════════════════════════════════════════════════════════════════
    # Section 5 — API Error Rate
    # ════════════════════════════════════════════════════════════════════════
    st.markdown("#### ⚠️ API Error Rate")

    err_cols = st.columns(4)
    err_data = [
        ("Total Agent Calls",  str(e["total_agent_calls"]),  "2 per completed run", "📞"),
        ("API Errors",         str(e["total_api_errors"]),   "watsonx.ai call failures", "❌"),
        ("API Error Rate",     f"{e['api_error_rate']}%",    "errors / agent calls", "📉"),
        ("Aborted Runs",       str(p["aborted_runs"]),       "blocked before API", "🚫"),
    ]
    for col, (label, val, sub, icon) in zip(err_cols, err_data):
        with col:
            color = _C_ERR if val not in ("0", "0.0%", "0%") else _C_OK
            st.markdown(_kpi_card(icon, label, val, sub, color),
                        unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Error breakdown table
    err_bd = get_error_breakdown(run_log)
    err_df = pd.DataFrame([
        {"Category": "Clean runs (no errors)",         "Count": err_bd["clean_runs"]},
        {"Category": "Pathologist Agent API errors",   "Count": err_bd["path_errors"]},
        {"Category": "Extension Officer API errors",   "Count": err_bd["ext_errors"]},
        {"Category": "Runs aborted by guardrails",     "Count": err_bd["aborted"]},
    ])
    st.dataframe(err_df, use_container_width=True, hide_index=True)
    st.markdown("---")

    # ════════════════════════════════════════════════════════════════════════
    # Section 6 — Guardrail Intervention Rate
    # ════════════════════════════════════════════════════════════════════════
    st.markdown("#### 🛡️ Guardrail Intervention Rate")

    grd_cols = st.columns(4)
    grd_det = get_guardrail_detail(run_log)
    grd_data = [
        ("Total Interventions",  str(g["total_hits"]),        "all guardrail layers", "🛡️"),
        ("Runs Affected",        str(g["runs_with_hits"]),    f"of {p['total_runs']} runs", "📋"),
        ("Intervention Rate",    f"{g['guardrail_rate']}%",   "runs with any hit", "📊"),
        ("Pre-pipeline Blocks",  str(grd_det["aborted_hits"]),"input / security", "🚫"),
    ]
    for col, (label, val, sub, icon) in zip(grd_cols, grd_data):
        with col:
            st.markdown(_kpi_card(icon, label, val, sub), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Guardrail hits per run bar chart
    if run_log:
        grd_labels = [f"Run {i+1}" for i in range(len(run_log))]
        grd_hits   = [r["guardrail_hits"] for r in run_log]
        grd_colors = [_C_ERR if h > 0 else _C_OK for h in grd_hits]

        fig_grd = go.Figure(go.Bar(
            x=grd_labels, y=grd_hits,
            marker_color=grd_colors,
            text=grd_hits, textposition="outside",
        ))
        fig_grd.update_layout(
            **_layout(title="Guardrail Hits per Run"),
            xaxis=dict(title="", showgrid=False),
            yaxis=dict(title="Interventions", gridcolor=_C_GRID),
            showlegend=False,
        )
        st.plotly_chart(fig_grd, use_container_width=True)

    st.markdown("---")

    # ════════════════════════════════════════════════════════════════════════
    # Section 7 — Hallucination Risk Evaluation
    # ════════════════════════════════════════════════════════════════════════
    st.markdown("#### 🔍 Hallucination Risk Evaluation")

    _notice(
        "**Measurement method:** The output guardrail applies a pattern-matching "
        "risk scorer to each LLM response. It counts matched signals such as "
        "fabricated statistics, contradictory confidence phrases, and vague "
        "attributions. Score ≥ 3 blocks the response. "
        "**This is a risk indicator — not ground-truth accuracy.** "
        "Ground-truth evaluation requires a labelled crop-disease reference dataset "
        "which is not available in-session."
    )

    hall_cols = st.columns(3)
    hall_data = [
        ("Runs Checked",      str(h["total_checked"]),    "completed runs", "🔬"),
        ("Flagged Responses", str(h["flagged_count"]),    "risk score > 0", "⚠️"),
        ("Flagged Rate",      f"{h['flagged_rate']}%",    "indicator only", "📊"),
    ]
    for col, (label, val, sub, icon) in zip(hall_cols, hall_data):
        with col:
            color = _C_ERR if h["flagged_count"] > 0 and label != "Runs Checked" else "#2d5a27"
            st.markdown(_kpi_card(icon, label, val, sub, color),
                        unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    hall_series = get_hallucination_series(run_log)
    if hall_series["labels"]:
        fig_hall = go.Figure()
        bar_colors = [_C_ERR if s > 0 else _C_OK for s in hall_series["scores"]]
        fig_hall.add_trace(go.Bar(
            x=hall_series["labels"], y=hall_series["scores"],
            marker_color=bar_colors,
            text=hall_series["scores"], textposition="outside",
            name="Risk Score",
        ))
        # Threshold reference line
        fig_hall.add_hline(
            y=3, line_dash="dash", line_color=_C_ERR,
            annotation_text="Block threshold (score=3)",
            annotation_position="top right",
        )
        fig_hall.update_layout(
            **_layout(title="Hallucination Risk Score per Run"),
            xaxis=dict(title="", showgrid=False),
            yaxis=dict(title="Risk Score (signal count)", gridcolor=_C_GRID,
                       range=[0, max(max(hall_series["scores"] or [0]) + 1, 5)]),
            showlegend=False,
        )
        st.plotly_chart(fig_hall, use_container_width=True)

    st.markdown("---")

    # ════════════════════════════════════════════════════════════════════════
    # Section 8 — Cost Tracking
    # ════════════════════════════════════════════════════════════════════════
    st.markdown("#### 💰 Cost Tracking")

    _notice(
        f"**Pricing source:** IBM watsonx.ai published rate for "
        f"ibm/granite-vision-3-2-2b (output: ${c['rate_per_1k_usd']}/1K tokens). "
        "The SDK currently returns completion tokens only; actual charges may differ. "
        "Always verify against your IBM Cloud usage dashboard."
    )

    cost_cols = st.columns(4)
    cost_data = [
        ("Estimated Total",       f"${c['total_usd']:.4f}",  "USD this session",       "💰"),
        ("Pathologist Agent",     f"${c['path_usd']:.4f}",   f"{t['path_total']:,} tokens", "🔬"),
        ("Extension Officer",     f"${c['ext_usd']:.4f}",    f"{t['ext_total']:,} tokens",  "💡"),
        ("Rate Used",             f"${c['rate_per_1k_usd']}", "per 1K output tokens",  "📋"),
    ]
    for col, (label, val, sub, icon) in zip(cost_cols, cost_data):
        with col:
            st.markdown(_kpi_card(icon, label, val, sub), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Cost breakdown pie
    if c["path_usd"] > 0 or c["ext_usd"] > 0:
        fig_cost = go.Figure(go.Pie(
            labels=["Pathologist Agent", "Extension Officer"],
            values=[c["path_usd"], c["ext_usd"]],
            marker_colors=[_C_PATH, _C_EXT],
            hole=0.5,
            textinfo="label+percent",
        ))
        fig_cost.update_layout(
            **_layout(title="Estimated Cost Breakdown by Agent"),
            showlegend=False,
        )
        cost_chart_col, cost_note_col = st.columns([1, 1])
        with cost_chart_col:
            st.plotly_chart(fig_cost, use_container_width=True)
        with cost_note_col:
            st.markdown("""
**Cost assumptions:**
- Rate: IBM watsonx.ai output rate for `ibm/granite-vision-3-2-2b`
- Token count: completion tokens reported by SDK (not input tokens)
- Currency: USD
- Input tokens for vision calls (image encoding) are **not counted** as the SDK does not report them separately

**To verify actual charges:** Log in to [IBM Cloud](https://cloud.ibm.com) → Usage → watsonx.ai
            """)

    st.markdown("---")

    # ════════════════════════════════════════════════════════════════════════
    # Section 9 — Run History Table
    # ════════════════════════════════════════════════════════════════════════
    st.markdown("#### 📋 Run History")

    run_df = get_run_table(run_log)
    if not run_df.empty:
        st.dataframe(
            run_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Run":           st.column_config.NumberColumn(format="%d"),
                "Pipeline (ms)": st.column_config.NumberColumn(format="%.0f ms"),
                "Tokens":        st.column_config.NumberColumn(format="%d"),
                "Status": st.column_config.TextColumn(),
                "Pathologist": st.column_config.TextColumn(),
                "Ext Officer": st.column_config.TextColumn(),
            },
        )

    st.markdown("---")

    # ════════════════════════════════════════════════════════════════════════
    # Section 10 — Unavailable Metrics
    # ════════════════════════════════════════════════════════════════════════
    st.markdown("#### ⛔ Metrics Not Available in This Session")
    st.markdown(
        "The following metrics require external ground-truth data, human "
        "feedback, or SDK features not available in the current deployment. "
        "They are listed here for transparency."
    )

    for item in kpis.get("unavailable", []):
        _unavailable_badge(item["metric"], item["reason"])

    st.markdown("---")

    # ════════════════════════════════════════════════════════════════════════
    # Section 11 — Controls
    # ════════════════════════════════════════════════════════════════════════
    ctrl_col, _ = st.columns([1, 2])
    with ctrl_col:
        if st.button("🗑️ Clear Session Metrics", type="secondary",
                     use_container_width=True):
            st.session_state["run_log"]  = []
            st.session_state["eval_log"] = []
            st.session_state.pop("last_result", None)
            st.session_state.pop("last_note", None)
            st.rerun()

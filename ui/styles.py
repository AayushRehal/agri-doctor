"""
ui/styles.py
=============
Shared CSS theme for Agri Doctor — green and earth-tone agricultural palette.

Usage:
    from ui.styles import GLOBAL_CSS
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
"""

GLOBAL_CSS = """
<style>
/* ── Global background & font ───────────────────────── */
.stApp {
    background-color: #f4f7f0;
    font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
}

/* ── Sidebar ────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background-color: #2d5a27;
}
[data-testid="stSidebar"] * {
    color: #e8f5e3 !important;
}

/* ── Top header bar ─────────────────────────────────── */
.agri-header {
    background: linear-gradient(135deg, #2d5a27 0%, #4a8c3f 60%, #6aaa5e 100%);
    padding: 24px 32px;
    border-radius: 14px;
    margin-bottom: 24px;
    color: white;
}
.agri-header h1 {
    margin: 0;
    font-size: 2.0rem;
    font-weight: 700;
    color: white !important;
}
.agri-header p {
    margin: 6px 0 0 0;
    font-size: 0.95rem;
    color: #d4edcc;
}

/* ── Metric cards ───────────────────────────────────── */
.metric-card {
    background: white;
    border: 1px solid #d4e8cc;
    border-radius: 12px;
    padding: 18px 16px;
    text-align: center;
    box-shadow: 0 2px 6px rgba(45,90,39,0.08);
}
.metric-card .card-icon  { font-size: 1.9rem; margin-bottom: 4px; }
.metric-card .card-label { font-size: 0.75rem; color: #6b7c61; text-transform: uppercase; letter-spacing: 0.05em; }
.metric-card .card-value { font-size: 1.75rem; font-weight: 700; color: #2d5a27; margin-top: 2px; }
.metric-card .card-unit  { font-size: 0.8rem;  color: #9ab88f; }

/* ── Diagnosis result card ──────────────────────────── */
.diagnosis-card {
    background: white;
    border-left: 5px solid #4a8c3f;
    border-radius: 10px;
    padding: 20px 24px;
    box-shadow: 0 2px 8px rgba(45,90,39,0.08);
    margin-top: 16px;
}
.diagnosis-card h3 {
    color: #2d5a27;
    margin-top: 0;
}

/* ── Severity badge colours ─────────────────────────── */
.badge {
    display: inline-block;
    padding: 3px 12px;
    border-radius: 20px;
    font-size: 0.82rem;
    font-weight: 600;
}
.badge-mild     { background: #d4edcc; color: #2d5a27; }
.badge-moderate { background: #fff3cd; color: #856404; }
.badge-severe   { background: #fde8e8; color: #991b1b; }
.badge-none     { background: #d4edcc; color: #2d5a27; }
.badge-unknown  { background: #e9ecef; color: #495057; }

/* ── Recommendation sections ────────────────────────── */
.rec-section {
    background: white;
    border: 1px solid #e0ecd8;
    border-radius: 10px;
    padding: 16px 20px;
    margin-bottom: 12px;
    box-shadow: 0 1px 4px rgba(45,90,39,0.05);
}
.rec-section h4 {
    color: #2d5a27;
    margin: 0 0 8px 0;
    font-size: 1.0rem;
}
.rec-section p {
    color: #3d4f38;
    margin: 0;
    line-height: 1.6;
}

/* ── Upload zone ────────────────────────────────────── */
[data-testid="stFileUploader"] {
    border: 2px dashed #4a8c3f !important;
    border-radius: 12px !important;
    background: #f9fbf7 !important;
}

/* ── Primary button ─────────────────────────────────── */
.stButton > button[kind="primary"] {
    background-color: #2d5a27 !important;
    border-color: #2d5a27 !important;
    color: white !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    padding: 0.5rem 1.5rem !important;
}
.stButton > button[kind="primary"]:hover {
    background-color: #4a8c3f !important;
    border-color: #4a8c3f !important;
}

/* ── Info/warning boxes ─────────────────────────────── */
.info-box {
    background: #e8f5e3;
    border: 1px solid #b8dba8;
    border-radius: 8px;
    padding: 12px 16px;
    color: #2d5a27;
    font-size: 0.9rem;
}

/* ── Guardrail event badge ───────────────────────────── */
.guardrail-pass   { color: #2d5a27; font-weight: 600; }
.guardrail-block  { color: #991b1b; font-weight: 600; }

/* ── Tab content spacing ────────────────────────────── */
.block-container {
    padding-top: 1.5rem;
    padding-bottom: 2rem;
}
</style>
"""


def severity_badge(severity: str) -> str:
    """Return an HTML badge span for a severity level."""
    sev = (severity or "").strip().lower()
    class_map = {
        "mild":     "badge-mild",
        "moderate": "badge-moderate",
        "severe":   "badge-severe",
        "none":     "badge-none",
    }
    css_class = class_map.get(sev, "badge-unknown")
    label = severity.title() if severity else "Unknown"
    return f'<span class="badge {css_class}">{label}</span>'


def metric_card_html(icon: str, label: str, value: str, unit: str = "") -> str:
    """Return HTML for a single metric card."""
    return (
        f'<div class="metric-card">'
        f'<div class="card-icon">{icon}</div>'
        f'<div class="card-label">{label}</div>'
        f'<div class="card-value">{value} <span class="card-unit">{unit}</span></div>'
        f'</div>'
    )

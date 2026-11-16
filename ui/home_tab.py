"""
ui/home_tab.py
==============
Streamlit Home Tab — image upload, farmer note input, and diagnosis display.

Renders the main Agri Doctor diagnosis workflow:
  1. File upload widget
  2. Optional farmer's note
  3. "Analyse Crop" button → triggers Orchestrator
  4. Diagnosis result card
  5. Escalation events (Severe disease alerts from agricultural safety guardrail)
"""

import streamlit as st
from agents.orchestrator import Orchestrator
from ui.styles import severity_badge


def render():
    """Render the Home / Diagnosis tab."""

    st.markdown("### 🔬 Crop Disease Diagnosis")
    st.markdown(
        "Upload a clear photo of the affected crop, add an optional note, "
        "and click **Analyse Crop** to get an AI-powered diagnosis."
    )
    st.markdown("---")

    # ── Upload + Note input ───────────────────────────────────────────────────
    col_upload, col_note = st.columns([1, 1], gap="large")

    with col_upload:
        st.markdown("**📸 Upload Crop Image**")
        uploaded_file = st.file_uploader(
            label="Crop image",
            type=["jpg", "jpeg", "png", "webp"],
            help="Supported formats: JPEG, PNG, WEBP · Maximum size: 10 MB",
            label_visibility="collapsed",
        )
        if uploaded_file:
            st.image(uploaded_file, caption="Uploaded image", use_container_width=True)

    with col_note:
        st.markdown("**📝 Farmer's Note** _(optional)_")
        farmer_note = st.text_area(
            label="Farmer's note",
            placeholder=(
                "Describe what you have observed — e.g. 'Leaves started yellowing "
                "from the edges 3 days ago. Some brown spots appeared on the stem.'"
            ),
            max_chars=500,
            height=200,
            label_visibility="collapsed",
        )
        st.caption(f"{len(farmer_note)}/500 characters")

    st.markdown("---")

    # ── Analyse button ────────────────────────────────────────────────────────
    analyse_col, _ = st.columns([1, 2])
    with analyse_col:
        analyse_clicked = st.button(
            "🔬 Analyse Crop",
            type="primary",
            use_container_width=True,
            disabled=(uploaded_file is None),
        )

    if uploaded_file is None:
        st.info("💡 Upload a crop image above to enable analysis.")
        return

    if not analyse_clicked:
        # Show previous result if available
        if st.session_state.get("last_result"):
            _render_diagnosis(st.session_state["last_result"])
        return

    # ── Run the pipeline ──────────────────────────────────────────────────────
    with st.spinner("🔬 Pathologist Agent is analysing the crop image…"):
        orchestrator = Orchestrator()
        result = orchestrator.run(uploaded_file, farmer_note)

    # Store for other tabs
    st.session_state["last_result"]    = result
    st.session_state["last_note"]      = farmer_note

    # ── Show result or error ──────────────────────────────────────────────────
    if result.get("error") and not result.get("diagnosis", {}).get("disease_name"):
        st.error(f"❌ Analysis failed: {result['error']}")
        _render_guardrail_events(result.get("guardrail_events", []))
        return

    _render_diagnosis(result)
    st.success("✅ Analysis complete — see the **Recommendations** tab for treatment advice.")


# ── Private helpers ───────────────────────────────────────────────────────────

def _render_diagnosis(result: dict):
    """Render the structured diagnosis card."""
    diagnosis = result.get("diagnosis", {})
    if not diagnosis:
        return

    if diagnosis.get("error"):
        st.warning(f"⚠️ Diagnosis error: {diagnosis['error']}")
        return

    disease    = diagnosis.get("disease_name",      "Unknown")
    confidence = diagnosis.get("confidence",        "N/A")
    severity   = diagnosis.get("severity",          "Unknown")
    symptoms   = diagnosis.get("symptoms_observed", "N/A")
    latency    = diagnosis.get("latency_ms",        0)
    tokens     = diagnosis.get("tokens_used",       0)

    st.markdown("#### 🧪 Pathologist Agent — Diagnosis Result")

    badge_html = severity_badge(severity)

    st.markdown(
        f"""
        <div class="diagnosis-card">
            <h3>🌿 {disease}</h3>
            <p><strong>Confidence:</strong> {confidence} &nbsp;&nbsp;
               <strong>Severity:</strong> {badge_html}</p>
            <hr style="border-color:#e0ecd8; margin: 12px 0;">
            <p><strong>Symptoms Observed:</strong><br>{symptoms}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("📊 Model Metrics"):
        m1, m2 = st.columns(2)
        m1.metric("Latency", f"{latency:,.0f} ms")
        m2.metric("Tokens Used", tokens if tokens else "N/A")

    with st.expander("📄 Raw Model Response"):
        st.code(diagnosis.get("raw_response", "No response captured."), language=None)

    _render_guardrail_events(result.get("guardrail_events", []))
    _render_escalation_events(result.get("escalation_events", []))


def _render_escalation_events(events: list):
    """Render agricultural severity escalation alerts if any are triggered."""
    if not events:
        return
    # Only show if at least one event is a WARNING/BLOCK (i.e. escalation fired)
    triggered = [e for e in events if not e.get("passed") or
                 e.get("severity") in ("WARNING", "BLOCK")]
    if not triggered:
        return
    for event in triggered:
        st.warning(
            f"🚨 **Escalation Alert — {event.get('layer', 'Agricultural Safety')}**: "
            f"{event.get('reason', '')}"
        )


def _render_guardrail_events(events: list):
    """Render guardrail events if any are present."""
    if not events:
        return
    with st.expander("🛡️ Guardrail Events"):
        for event in events:
            if event.get("passed"):
                st.markdown(
                    f'<span class="guardrail-pass">✅ {event.get("layer", "")}</span>: '
                    f'{event.get("reason", "")}',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<span class="guardrail-block">❌ {event.get("layer", "")}</span>: '
                    f'{event.get("reason", "")}',
                    unsafe_allow_html=True,
                )

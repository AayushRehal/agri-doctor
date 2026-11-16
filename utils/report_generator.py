"""
utils/report_generator.py
==========================
Builds a downloadable Markdown report from an Agri Doctor analysis result.

Public function:
  - build_report(result: dict, farmer_note: str) -> str
"""

from datetime import datetime


def build_report(result: dict, farmer_note: str = "") -> str:
    """
    Serialise a completed Orchestrator result into a Markdown string.

    Args:
        result:      The combined result dict returned by Orchestrator.run().
        farmer_note: The original note supplied by the farmer.

    Returns:
        A Markdown-formatted string ready for st.download_button().
    """
    now           = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    run_id        = result.get("run_id", "N/A")
    diagnosis     = result.get("diagnosis", {})
    recs          = result.get("recommendations", {})
    guardrails    = result.get("guardrail_events", [])
    escalations   = result.get("escalation_events", [])
    agri_safety   = result.get("agri_safety_events", [])

    lines = [
        "# 🌿 Agri Doctor — Crop Disease Analysis Report",
        "",
        f"**Generated:** {now}  ",
        f"**Run ID:** `{run_id}`",
        "",
        "---",
        "",
        "## 📝 Farmer's Note",
        "",
        farmer_note.strip() if farmer_note.strip() else "_No note provided._",
        "",
        "---",
        "",
        "## 🔬 Pathologist Agent — Diagnosis",
        "",
    ]

    # Diagnosis fields
    if diagnosis.get("error"):
        lines.append(f"> ⚠️ **Error during diagnosis:** {diagnosis['error']}")
    else:
        disease    = diagnosis.get("disease_name",       "Unknown")
        confidence = diagnosis.get("confidence",         "N/A")
        severity   = diagnosis.get("severity",           "N/A")
        symptoms   = diagnosis.get("symptoms_observed",  "N/A")
        raw        = diagnosis.get("raw_response",       "")

        lines += [
            f"| Field | Value |",
            f"|---|---|",
            f"| **Disease / Condition** | {disease} |",
            f"| **Confidence** | {confidence} |",
            f"| **Severity** | {severity} |",
            f"| **Symptoms Observed** | {symptoms} |",
            "",
            "### Full Model Response",
            "",
            f"```",
            raw.strip(),
            "```",
        ]

    lines += [
        "",
        "---",
        "",
        "## 💡 Extension Officer Agent — Recommendations",
        "",
    ]

    # Recommendation fields
    if recs.get("error"):
        lines.append(f"> ⚠️ **Error during recommendation:** {recs['error']}")
    else:
        treatment  = recs.get("treatment",         "N/A")
        prevention = recs.get("prevention",        "N/A")
        chemicals  = recs.get("safe_chemicals",    "N/A")
        advisory   = recs.get("farmer_advisory",   "N/A")
        raw_rec    = recs.get("raw_response",       "")

        lines += [
            f"### Treatment",
            f"{treatment}",
            "",
            f"### Prevention",
            f"{prevention}",
            "",
            f"### Safe Chemicals / Inputs",
            f"{chemicals}",
            "",
            f"### Farmer Advisory",
            f"{advisory}",
            "",
            "### Full Model Response",
            "",
            "```",
            raw_rec.strip(),
            "```",
        ]

    # Guardrail events
    lines += [
        "",
        "---",
        "",
        "## 🛡️ Guardrail Events",
        "",
    ]
    if guardrails:
        for event in guardrails:
            status = "✅ Passed" if event.get("passed") else "❌ Blocked"
            lines.append(f"- **{event.get('layer', 'Unknown')}**: {status} — {event.get('reason', '')}")
    else:
        lines.append("_No guardrail interventions recorded._")

    # Escalation events
    lines += [
        "",
        "---",
        "",
        "## 🚨 Severity Escalation Alerts",
        "",
    ]
    triggered = [e for e in escalations
                 if not e.get("passed") or e.get("severity") in ("WARNING", "BLOCK")]
    if triggered:
        for event in triggered:
            sev   = event.get("severity", "")
            layer = event.get("layer", "")
            lines.append(f"- **[{sev}] {layer}**: {event.get('reason', '')}")
    else:
        lines.append("_No escalation alerts triggered._")

    # Agricultural safety events
    lines += [
        "",
        "---",
        "",
        "## 🌿 Agricultural Safety Checks",
        "",
    ]
    if agri_safety:
        for event in agri_safety:
            status = "✅ Passed" if event.get("passed") else "⚠️ Flagged"
            sev    = event.get("severity", "INFO")
            layer  = event.get("layer", "Unknown")
            lines.append(f"- **{layer}** [{sev}]: {status} — {event.get('reason', '')}")
    else:
        lines.append("_No agricultural safety events recorded._")

    # Footer disclaimer
    lines += [
        "",
        "---",
        "",
        "> **⚠️ Disclaimer:** This report is generated by an AI system (IBM Granite Vision) "
        "for informational purposes only. It does not constitute professional agricultural "
        "advice. Always consult a qualified agricultural extension officer or plant "
        "pathologist before applying treatments or chemicals to crops.",
        "",
        "_Made with Agri Doctor — IBM watsonx.ai + IBM Granite Vision_",
    ]

    return "\n".join(lines)

"""Postmortem generation: a deterministic record (timeline, tools, approvals) plus
an LLM-written narrative (summary, root cause, resolution, prevention).

The file is always written, even when the LLM is down or the agent escalated,
and rewritten when the resolved notice arrives later."""
import json
from datetime import datetime
from typing import Any

from app.audit import redact
from app.incidents import store as incident_store
from app.llm import LLM, LLMUnavailable

NARRATIVE_SYSTEM = (
    "You write concise, factual incident postmortems for a small business's Odoo system. "
    "Use only the facts in the record you are given; if something is unknown, say so. "
    "Output Markdown with exactly these sections: '## Summary', '## Root cause', "
    "'## Resolution', '## Prevention'. Prevention lists 2-4 concrete follow-ups."
)


def _fmt_ts(ts: str | None) -> str:
    if not ts:
        return "-"
    try:
        return datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M:%S UTC")
    except ValueError:
        return ts


def _timeline(incident: dict[str, Any]) -> list[str]:
    rows = []
    for e in incident["events"]:
        k = e["kind"]
        if k == "alert_received":
            what = f"Alert **{incident['alertname']}** received: {e.get('summary', '')}"
        elif k == "duplicate_alert":
            what = "Duplicate alert deduplicated"
        elif k == "agent_started":
            what = "SRE agent started investigating"
        elif k == "tool_call":
            what = f"Tool `{e['tool']}` -> {e['status']}"
        elif k == "approval_requested":
            what = f"Approval requested for `{e['tool']}` {json.dumps(e.get('args', {}))}"
        elif k == "approval_decided":
            who = f" by {e['decided_by']}" if e.get("decided_by") else ""
            what = f"Approval for `{e['tool']}`: **{e['status']}**{who}"
        elif k == "alert_resolved":
            what = "Alert resolved (Alertmanager)"
        elif k == "agent_finished":
            what = f"Agent finished: {e.get('stop_reason', '')} (status {e.get('status', '')})"
        elif k == "llm_error":
            what = f"LLM unavailable: {e.get('error', '')}"
        else:
            continue
        rows.append(f"| {_fmt_ts(e['ts'])} | {what} |")
    return rows


def _record_markdown(incident: dict[str, Any]) -> str:
    actions = [e for e in incident["events"] if e["kind"] == "tool_call" and e.get("approval_id")]
    lines = [
        f"# Postmortem: {incident['alertname']} ({incident['id']})",
        "",
        f"- **Status:** {incident['status']}",
        f"- **Severity:** {incident['severity']}",
        f"- **Started:** {_fmt_ts(incident['created_at'])}",
        f"- **Resolved (alert cleared):** {_fmt_ts(incident.get('resolved_at'))}",
        f"- **Duplicate alerts merged:** {incident.get('duplicates', 0)}",
        "",
    ]
    return "\n".join(lines), actions


def _narrative(incident: dict[str, Any], llm: LLM | None) -> str:
    cached = incident.get("postmortem_narrative")
    if cached:
        return cached
    fallback = (
        "## Summary\n"
        f"Alert {incident['alertname']} fired and the SRE agent investigated "
        f"(final status: {incident['status']}).\n\n"
        "## Root cause\n"
        + (incident.get("diagnosis") or "No diagnosis was produced.") + "\n\n"
        "## Resolution\n"
        + ("An approved action was executed; see the timeline.\n\n"
           if any(e.get("approval_id") and e.get("status") == "ok"
                  for e in incident["events"] if e["kind"] == "tool_call")
           else "No automated fix was applied. A human should review the diagnosis above.\n\n")
        + "## Prevention\n"
        "Not generated automatically (the language model was unavailable); review the timeline.\n"
    )
    if llm is None:
        return fallback
    record = {k: incident.get(k) for k in
              ("alertname", "severity", "status", "created_at", "resolved_at", "diagnosis")}
    record["events"] = [
        {k: v for k, v in e.items() if k in ("ts", "kind", "tool", "status", "summary", "args",
                                              "output", "text", "stop_reason", "decided_by")}
        for e in incident["events"]
    ]
    try:
        reply = llm.complete(
            NARRATIVE_SYSTEM,
            [{"role": "user", "content": "Incident record (JSON):\n" + json.dumps(record, default=str)[:20000]}],
            tools=None, max_tokens=1200)
        return reply.text.strip() or fallback
    except LLMUnavailable:
        return fallback


def write_postmortem(incident_id: str, llm: LLM | None = None) -> str:
    """Create or refresh incidents/<id>.md and return its file name."""
    incident = incident_store.get(incident_id)
    assert incident is not None
    narrative = _narrative(incident, llm)
    if not incident.get("postmortem_narrative"):
        incident_store.update(incident_id, postmortem_narrative=narrative)
        incident = incident_store.get(incident_id)

    header, actions = _record_markdown(incident)
    body = [header, narrative, "", "## Timeline", "", "| Time | Event |", "|---|---|"]
    body += _timeline(incident)
    body += ["", "## Actions taken", ""]
    if actions:
        for e in actions:
            body.append(f"- `{e['tool']}` {json.dumps(e.get('input', {}))} -> {e['status']} "
                        f"(approval `{e['approval_id']}`)")
    else:
        body.append("- None. No action tool was executed.")
    body += ["", "## Evidence", ""]
    evidence = [e for e in incident["events"] if e["kind"] == "tool_call" and e["status"] == "ok"]
    if evidence:
        for e in evidence[:12]:
            body.append(f"- `{e['tool']}` {json.dumps(e.get('input', {}))}: "
                        f"{str(e.get('output', ''))[:240]}")
    else:
        body.append("- No tool evidence was collected.")

    name = f"{incident['id']}.md"
    path = incident_store.directory / name
    path.write_text(redact("\n".join(body) + "\n"), encoding="utf-8")
    incident_store.update(incident_id, postmortem=name)
    return name

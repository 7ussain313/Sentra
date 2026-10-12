"""SRE agent tests with a scripted LLM and fake tool backends (no Docker/DB/Odoo/API key)."""
import dataclasses
import json
import threading
import time

import pytest

from app import approvals, audit, incidents, sre_agent, tools
from app.config import get_settings
from app.llm import LLMReply, LLMUnavailable, ToolCall
from app.tools import registry


# ------------------------------------------------------------------ helpers
class ScriptedLLM:
    """Returns the scripted replies in order, then plain text forever."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, system, messages, tools=None, max_tokens=2048):
        self.calls.append({"tools": bool(tools), "n_messages": len(messages)})
        if self.replies:
            return self.replies.pop(0)
        return text("(no more script)")


def text(t):
    return LLMReply(text=t, blocks=[{"type": "text", "text": t}])


def use(name, args=None, call_id=None, preface=""):
    cid = call_id or f"tu_{name}_{time.monotonic_ns()}"
    blocks = ([{"type": "text", "text": preface}] if preface else []) + [
        {"type": "tool_use", "id": cid, "name": name, "input": args or {}}]
    return LLMReply(text=preface, tool_calls=[ToolCall(cid, name, args or {})], blocks=blocks,
                    stop_reason="tool_use")


def fake_tool(monkeypatch, name, fn):
    monkeypatch.setitem(registry.TOOLS, name, dataclasses.replace(registry.TOOLS[name], fn=fn))


def make_alert(name="OdooDown"):
    return {"status": "firing", "labels": {"alertname": name, "severity": "critical"},
            "annotations": {"summary": f"{name} summary", "description": f"{name} description"},
            "startsAt": "2026-10-12T10:00:00Z"}


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_DIR", str(tmp_path / "audit"))
    monkeypatch.setenv("INCIDENTS_DIR", str(tmp_path / "incidents"))
    monkeypatch.setenv("MAX_STEPS", "6")
    get_settings.cache_clear()
    incidents.store._items = {}
    incidents.store._loaded_from = None
    approvals.store._items.clear()
    sre_agent.install_approval_gate()
    # Read tools return canned evidence; action tools record that they ran.
    fake_tool(monkeypatch, "check_container_status", lambda p: [
        {"service": "odoo", "state": "exited", "health": "none", "restarts": 0, "exit_code": 137}])
    fake_tool(monkeypatch, "read_logs", lambda p: {"service": p.service, "lines": 2, "text": "boom"})
    fake_tool(monkeypatch, "query_metrics", lambda p: {"series": [{"value": "0"}]})
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture
def ran(monkeypatch):
    calls = []
    fake_tool(monkeypatch, "restart_service",
              lambda p: calls.append(("restart", p.service)) or {"success": True, "state": "running"})
    fake_tool(monkeypatch, "kill_long_running_query",
              lambda p: calls.append(("kill", p.pid)) or {"success": True, "pid": p.pid})
    fake_tool(monkeypatch, "clear_odoo_cache",
              lambda p: calls.append(("cache",)) or {"success": True})
    return calls


def new_incident(name="OdooDown"):
    return incidents.store.create(name, make_alert(name))


def decide_when_pending(approve, delay=0.0):
    def run():
        for _ in range(200):
            pend = approvals.store.pending()
            if pend:
                time.sleep(delay)
                approvals.store.decide(pend[0].id, approve, "tester")
                return
            time.sleep(0.02)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def statuses(env_dir):
    f = env_dir / "audit" / "audit.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


# --------------------------------------------------------------------- tests
def test_read_only_diagnosis_creates_postmortem(env, ran):
    inc = new_incident()
    llm = ScriptedLLM([
        use("check_container_status", preface="Checking containers."),
        use("read_logs", {"service": "odoo", "lines": 50}),
        text("## Diagnosis\nOdoo was OOM-killed (high).\n## Evidence\n- exit_code 137\n"
             "## Proposed fix\nnone: escalate\n"),
        text("## Summary\nOdoo exited.\n## Root cause\nOOM.\n## Resolution\nNone.\n## Prevention\n- Add memory limit\n"),
    ])
    sre_agent.handle_incident(inc["id"], llm)
    got = incidents.store.get(inc["id"])
    assert got["status"] == "diagnosed"
    assert "OOM-killed" in got["diagnosis"]
    assert ran == []                                     # no action ran
    kinds = [e["kind"] for e in got["events"]]
    assert kinds.count("tool_call") == 2 and "agent_finished" in kinds
    pm = (env / "incidents" / got["postmortem"]).read_text()
    assert "## Timeline" in pm and "## Root cause" in pm and "No action tool was executed" in pm
    assert "Add memory limit" in pm


def test_action_requires_and_uses_approval_then_verifies(env, ran):
    inc = new_incident()
    llm = ScriptedLLM([
        use("check_container_status"),
        use("restart_service", {"service": "odoo"}, preface="Odoo is down; restarting."),
        use("check_container_status"),                    # verification pass
        text("## Diagnosis\nOdoo crashed; restart fixed it.\n## Result\nRunning again.\n"),
        text("## Summary\nx\n## Root cause\ny\n## Resolution\nRestarted.\n## Prevention\n- z\n"),
    ])
    decide_when_pending(True)
    sre_agent.handle_incident(inc["id"], llm, approval_timeout=5)
    got = incidents.store.get(inc["id"])
    assert ran == [("restart", "odoo")]
    assert got["status"] == "fixed"
    assert got["proposed_action"] == {"tool": "restart_service", "args": {"service": "odoo"}}
    kinds = [e["kind"] for e in got["events"]]
    assert kinds.index("approval_requested") < kinds.index("approval_decided")
    restart = [e for e in got["events"] if e["kind"] == "tool_call" and e["tool"] == "restart_service"][0]
    assert restart["status"] == "ok" and restart["approval_id"]
    # the verification call came after the action
    last_tool = [e for e in got["events"] if e["kind"] == "tool_call"][-1]
    assert last_tool["tool"] == "check_container_status"
    ap = [a for a in audit_entries(env) if a.get("kind") == "approval" and a["status"] == "approved"]
    assert ap and ap[0]["user"] == "tester"
    assert "restart_service" in (env / "incidents" / got["postmortem"]).read_text()


def audit_entries(env):
    return statuses(env)


def test_rejected_action_does_not_run_and_agent_stops(env, ran):
    inc = new_incident()
    llm = ScriptedLLM([
        use("restart_service", {"service": "db"}),
        text("## Diagnosis\nDB restart proposed but rejected.\n"),     # finalize call
        text("## Summary\n..\n## Root cause\n..\n## Resolution\nNone\n## Prevention\n- ..\n"),
    ])
    decide_when_pending(False)
    sre_agent.handle_incident(inc["id"], llm, approval_timeout=5)
    got = incidents.store.get(inc["id"])
    assert ran == []
    assert got["status"] == "escalated"
    finished = [e for e in got["events"] if e["kind"] == "agent_finished"][0]
    assert finished["stop_reason"] == "action_rejected"
    assert len([e for e in got["events"] if e["kind"] == "approval_requested"]) == 1  # no retry


def test_approval_timeout_cancels_action(env, ran):
    inc = new_incident()
    llm = ScriptedLLM([use("clear_odoo_cache"), text("## Diagnosis\nTimed out.\n"), text("## Summary\n.\n")])
    sre_agent.handle_incident(inc["id"], llm, approval_timeout=0.2)
    got = incidents.store.get(inc["id"])
    assert ran == []
    assert got["status"] == "escalated"
    assert [e for e in got["events"] if e["kind"] == "approval_decided"][0]["status"] == "timeout"


def test_step_limit_reports_evidence(env, ran):
    inc = new_incident()
    loops = [use("query_metrics", {"promql": "up"}) for _ in range(10)]
    llm = ScriptedLLM(loops[:6] + [text("## Diagnosis\nUnclear; step limit.\n"), text("## Summary\n.\n")])
    sre_agent.handle_incident(inc["id"], llm)
    got = incidents.store.get(inc["id"])
    assert got["status"] == "escalated"
    assert [e for e in got["events"] if e["kind"] == "agent_finished"][0]["stop_reason"] == "max_steps"
    assert len([e for e in got["events"] if e["kind"] == "tool_call"]) == 6
    assert "step limit" in got["diagnosis"].lower()


def test_model_cannot_bypass_gate_with_unlisted_or_invalid_calls(env, ran):
    inc = new_incident()
    llm = ScriptedLLM([
        use("shell_exec", {"cmd": "rm -rf /"}),
        use("restart_service", {"service": "grafana"}),   # not allowlisted: never reaches approval
        text("## Diagnosis\nDone.\n"),
        text("## Summary\n.\n"),
    ])
    sre_agent.handle_incident(inc["id"], llm, approval_timeout=1)
    got = incidents.store.get(inc["id"])
    assert ran == []
    assert not [e for e in got["events"] if e["kind"] == "approval_requested"]
    assert [e["status"] for e in got["events"] if e["kind"] == "tool_call"] == ["rejected", "rejected"]
    assert got["status"] == "diagnosed"


def test_llm_unavailable_still_produces_incident_and_postmortem(env, ran):
    inc = new_incident()

    def factory():
        raise LLMUnavailable("ANTHROPIC_API_KEY is not configured")

    sre_agent.set_llm_factory(factory)
    try:
        sre_agent.handle_incident(inc["id"])
    finally:
        sre_agent.set_llm_factory(sre_agent.default_llm)
    got = incidents.store.get(inc["id"])
    assert got["status"] == "agent_unavailable"
    assert "OdooDown description" in got["diagnosis"]
    assert (env / "incidents" / got["postmortem"]).exists()


def test_llm_failure_mid_incident_keeps_evidence(env, ran):
    class Flaky(ScriptedLLM):
        def complete(self, *a, **k):
            if len(self.calls) >= 1:
                raise LLMUnavailable("503")
            return super().complete(*a, **k)

    inc = new_incident()
    sre_agent.handle_incident(inc["id"], Flaky([use("check_container_status")]))
    got = incidents.store.get(inc["id"])
    assert got["status"] == "agent_unavailable"
    assert "check_container_status" in got["diagnosis"]
    assert got["postmortem"]


def test_alert_dedup_and_resolution(env):
    payload = {"status": "firing", "alerts": [make_alert()]}
    first = sre_agent.handle_alertmanager(payload, run=False)
    second = sre_agent.handle_alertmanager(payload, run=False)
    assert first == second and len(incidents.store.list()) == 1
    assert incidents.store.get(first[0])["duplicates"] == 1
    other = sre_agent.handle_alertmanager(
        {"alerts": [make_alert("PostgresConnectionsHigh")]}, run=False)
    assert other != first and len(incidents.store.list()) == 2
    resolved = dict(make_alert(), status="resolved", endsAt="2026-10-12T10:05:00Z")
    sre_agent.handle_alertmanager({"status": "resolved", "alerts": [resolved]}, run=False)
    got = incidents.store.get(first[0])
    assert got["resolved_at"] == "2026-10-12T10:05:00Z"
    assert "alert_resolved" in [e["kind"] for e in got["events"]]


def test_incidents_persist_across_restart(env):
    inc = new_incident()
    incidents.store._items = {}
    incidents.store._loaded_from = None
    assert incidents.store.get(inc["id"])["alertname"] == "OdooDown"


# -------------------------------------------------------- approval store
def test_approval_single_use_and_args_bound():
    a = approvals.store.request("kill_long_running_query", {"pid": 10}, "inc", timeout_seconds=30)
    approvals.store.decide(a.id, True, "u")
    assert approvals.store.check(a.id, "kill_long_running_query", {"pid": 11}) is False   # other args
    assert approvals.store.check(a.id, "restart_service", {"pid": 10}) is False           # other tool
    assert approvals.store.check(a.id, "kill_long_running_query", {"pid": 10}) is True
    assert approvals.store.check(a.id, "kill_long_running_query", {"pid": 10}) is False   # consumed


def test_approval_cannot_be_redecided_or_forged():
    a = approvals.store.request("clear_odoo_cache", {}, None, timeout_seconds=30)
    approvals.store.decide(a.id, False, "u")
    with pytest.raises(ValueError):
        approvals.store.decide(a.id, True, "u")
    assert approvals.store.check(a.id, "clear_odoo_cache", {}) is False
    assert approvals.store.check("nope", "clear_odoo_cache", {}) is False
    with pytest.raises(KeyError):
        approvals.store.decide("nope", True, "u")


def test_pending_approval_never_grants():
    a = approvals.store.request("clear_odoo_cache", {}, None, timeout_seconds=30)
    assert approvals.store.check(a.id, "clear_odoo_cache", {}) is False
    with pytest.raises(tools.ApprovalRequired):
        tools.call("clear_odoo_cache", {}, approval_id=a.id)

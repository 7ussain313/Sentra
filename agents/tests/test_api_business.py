"""HTTP API, web UI and business-agent tests (scripted LLM, fake tool backends)."""
import dataclasses
import threading
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import approvals, business_agent, incidents, sre_agent
from app.config import get_settings
from app.llm import LLMReply, LLMUnavailable, ToolCall
from app.tools import registry
from app.tools.base import ToolError
from app.tools.odoo import OdooAggregateInput, validate_domain


class Scripted:
    def __init__(self, replies):
        self.r = list(replies)
        self.systems = []

    def complete(self, system, messages, tools=None, max_tokens=2048):
        self.systems.append(system)
        return self.r.pop(0) if self.r else text("(end)")


def text(t):
    return LLMReply(text=t, blocks=[{"type": "text", "text": t}])


def use(name, args=None):
    cid = f"tu_{name}_{time.monotonic_ns()}"
    return LLMReply(tool_calls=[ToolCall(cid, name, args or {})],
                    blocks=[{"type": "tool_use", "id": cid, "name": name, "input": args or {}}])


def fake_tool(monkeypatch, name, fn):
    monkeypatch.setitem(registry.TOOLS, name, dataclasses.replace(registry.TOOLS[name], fn=fn))


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_DIR", str(tmp_path / "audit"))
    monkeypatch.setenv("INCIDENTS_DIR", str(tmp_path / "incidents"))
    monkeypatch.setenv("UI_USERNAME", "owner")
    monkeypatch.setenv("UI_PASSWORD", "correct-horse-battery")
    get_settings.cache_clear()
    incidents.store._items = {}
    incidents.store._loaded_from = None
    approvals.store._items.clear()
    sre_agent.install_approval_gate()
    fake_tool(monkeypatch, "check_container_status", lambda p: [{"service": "odoo", "state": "exited"}])
    yield
    get_settings.cache_clear()


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


AUTH = ("owner", "correct-horse-battery")


# ----------------------------------------------------------- auth & UI
@pytest.mark.parametrize("path", ["/ui", "/api/incidents", "/api/approvals", "/api/audit", "/metrics",
                                  "/alerts"])
def test_protected_routes_need_auth(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, auth=("owner", "wrong")).status_code == 401
    assert client.get(path, auth=AUTH).status_code == 200


def test_post_routes_need_auth(client):
    assert client.post("/api/ask", json={"question": "hello?"}).status_code == 401
    assert client.post("/api/approvals/x", json={"approve": True}).status_code == 401
    assert client.post("/webhook/alertmanager", json={"status": "firing", "alerts": []}).status_code == 401


def test_health_is_open(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_ui_serves_all_pages_and_never_uses_innerhtml(client):
    html = client.get("/ui", auth=AUTH).text
    for marker in ('data-tab="incidents"', 'data-tab="approvals"', 'data-tab="ask"', 'data-tab="audit"',
                   "Approve", "Reject"):
        assert marker in html
    assert "innerHTML" not in html and "outerHTML" not in html and "document.write" not in html


# ----------------------------------------------- approval flow over HTTP
def _run_incident_in_thread(llm, timeout=5):
    inc = incidents.store.create("OdooDown", {
        "labels": {"alertname": "OdooDown", "severity": "critical"},
        "annotations": {"summary": "down", "description": "down"}})
    t = threading.Thread(target=sre_agent.handle_incident, args=(inc["id"], llm, timeout), daemon=True)
    t.start()
    return inc["id"], t


def _wait_pending(client, n=200):
    for _ in range(n):
        pend = [a for a in client.get("/api/approvals", auth=AUTH).json() if a["status"] == "pending"]
        if pend:
            return pend[0]
        time.sleep(0.02)
    raise AssertionError("no pending approval appeared")


def test_incident_flow_through_web_api_approve(client, monkeypatch):
    ran = []
    fake_tool(monkeypatch, "restart_service", lambda p: ran.append(p.service) or {"success": True})
    llm = Scripted([use("check_container_status"), use("restart_service", {"service": "odoo"}),
                    use("check_container_status"), text("## Diagnosis\nRestarted.\n"), text("## Summary\n.\n")])
    inc_id, t = _run_incident_in_thread(llm)
    pending = _wait_pending(client)
    assert pending["tool"] == "restart_service" and pending["incident_id"] == inc_id
    detail = client.get(f"/api/incidents/{inc_id}", auth=AUTH).json()
    assert detail["status"] == "awaiting_approval"
    r = client.post(f"/api/approvals/{pending['id']}", json={"approve": True}, auth=AUTH)
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["decided_by"] == "owner"
    t.join(10)
    assert ran == ["odoo"]
    detail = client.get(f"/api/incidents/{inc_id}", auth=AUTH).json()
    assert detail["status"] == "fixed"
    pm = client.get(f"/api/incidents/{inc_id}/postmortem", auth=AUTH)
    assert pm.status_code == 200 and "restart_service" in pm.text
    # single use: the same approval cannot be decided again
    again = client.post(f"/api/approvals/{pending['id']}", json={"approve": True}, auth=AUTH)
    assert again.status_code == 409
    # the decision is in the audit log with the user
    log = client.get("/api/audit?limit=200", auth=AUTH).json()
    assert any(e.get("kind") == "approval" and e.get("status") == "approved" and e.get("user") == "owner"
               for e in log)


def test_rejected_action_never_runs(client, monkeypatch):
    ran = []
    fake_tool(monkeypatch, "kill_long_running_query", lambda p: ran.append(p.pid) or {"success": True})
    llm = Scripted([use("kill_long_running_query", {"pid": 4242}), text("## Diagnosis\nRejected.\n"),
                    text("## Summary\n.\n")])
    inc_id, t = _run_incident_in_thread(llm)
    pending = _wait_pending(client)
    assert client.post(f"/api/approvals/{pending['id']}", json={"approve": False}, auth=AUTH).status_code == 200
    t.join(10)
    assert ran == []
    assert client.get(f"/api/incidents/{inc_id}", auth=AUTH).json()["status"] == "escalated"


def test_unanswered_approval_times_out_and_cancels(client, monkeypatch):
    ran = []
    fake_tool(monkeypatch, "clear_odoo_cache", lambda p: ran.append(1) or {"success": True})
    llm = Scripted([use("clear_odoo_cache"), text("## Diagnosis\nNo answer.\n"), text("## Summary\n.\n")])
    inc_id, t = _run_incident_in_thread(llm, timeout=0.3)
    t.join(10)
    assert ran == []
    a = client.get("/api/approvals", auth=AUTH).json()[0]
    assert a["status"] == "timeout"
    late = client.post(f"/api/approvals/{a['id']}", json={"approve": True}, auth=AUTH)
    assert late.status_code == 409          # too late; cannot be resurrected
    assert ran == []


def test_unknown_approval_and_bad_body(client):
    assert client.post("/api/approvals/nope", json={"approve": True}, auth=AUTH).status_code == 404
    assert client.post("/api/approvals/nope", json={"approve": True, "x": 1}, auth=AUTH).status_code == 422


# ---------------------------------------------------------- business agent
def test_business_agent_gets_only_read_tools_and_current_date(client, monkeypatch):
    calls = []
    fake_tool(monkeypatch, "odoo_aggregate",
              lambda p: calls.append(p.model_dump()) or {"count": 1, "groups": [{"amount_total": 300.0}]})
    llm = Scripted([use("odoo_aggregate", {"model": "account.move", "aggregates": ["amount_total:sum"],
                                           "domain": [["move_type", "=", "out_invoice"]]}),
                    text("Revenue this week was $300.00 (invoiced).")])
    business_agent.set_llm_factory(lambda: llm)
    try:
        r = client.post("/api/ask", json={"question": "What was revenue this week?"}, auth=AUTH)
    finally:
        business_agent.set_llm_factory(business_agent.default_llm)
    body = r.json()
    assert r.status_code == 200 and body["status"] == "ok" and "$300.00" in body["answer"]
    assert body["steps"][0]["tool"] == "odoo_aggregate" and body["steps"][0]["status"] == "ok"
    assert calls and calls[0]["model"] == "account.move"
    assert date.today().isoformat() in llm.systems[0]


def test_business_agent_cannot_write_or_act(client, monkeypatch):
    ran = []
    fake_tool(monkeypatch, "restart_service", lambda p: ran.append(1) or {"success": True})
    llm = Scripted([use("restart_service", {"service": "odoo"}),
                    use("odoo_write", {"model": "account.move", "values": {}}),
                    text("I can only read data.")])
    out = business_agent.ask("please restart odoo and delete invoices", llm=llm)
    assert ran == []
    assert [s["status"] for s in out["steps"]] == ["rejected", "rejected"]
    assert set(business_agent.TOOL_NAMES) == {"odoo_search", "odoo_aggregate"}
    assert set(business_agent.TOOL_NAMES).isdisjoint(registry.ACTION_TOOLS)


def test_business_agent_unavailable_is_graceful(client):
    def factory():
        raise LLMUnavailable("no key")
    business_agent.set_llm_factory(factory)
    try:
        r = client.post("/api/ask", json={"question": "Which invoices are unpaid?"}, auth=AUTH)
    finally:
        business_agent.set_llm_factory(business_agent.default_llm)
    assert r.status_code == 200 and r.json()["status"] == "unavailable"
    assert "unavailable" in r.json()["answer"].lower()


def test_ask_validates_input(client):
    assert client.post("/api/ask", json={"question": "x"}, auth=AUTH).status_code == 422
    assert client.post("/api/ask", json={"question": "a" * 501}, auth=AUTH).status_code == 422
    assert client.post("/api/ask", json={"question": "hello there", "model": "x"}, auth=AUTH).status_code == 422


@pytest.mark.parametrize("kwargs", [
    {"model": "res.users", "aggregates": ["id:count"]},
    {"model": "account.move", "aggregates": ["amount_total:drop"]},
    {"model": "account.move", "aggregates": ["amount_total;sum"]},
    {"model": "account.move", "group_by": ["partner_id; x"]},
    {"model": "account.move", "group_by": ["a", "b", "c", "d"]},
    {"model": "account.move", "aggregates": ["id:count"], "order_by": "id; drop"},
    {"model": "account.move", "aggregates": ["id:count"], "limit": 1000},
])
def test_aggregate_input_rejected(kwargs):
    with pytest.raises(Exception):
        OdooAggregateInput(**kwargs)


def test_aggregate_accepts_valid_input():
    p = OdooAggregateInput(model="carwash.booking", group_by=["service_id", "scheduled_date:month"],
                           aggregates=["price:sum"], order_by="price desc", limit=5)
    assert p.limit == 5
    with pytest.raises(ToolError):
        validate_domain([["x", "=~", 1]])

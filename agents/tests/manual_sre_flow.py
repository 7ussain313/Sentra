"""Manual integration: real tools and containers, scripted model. Stops nothing itself:
run `docker compose stop odoo` first, then:  python tests/manual_sre_flow.py (inside the agents container).
Writes an incident + postmortem to incidents/ (delete them afterwards; the narrative is scripted)."""
import json
import threading
import time

from app import approvals, incidents, sre_agent
from app.llm import LLMReply, ToolCall


def text(t):
    return LLMReply(text=t, blocks=[{"type": "text", "text": t}])


def use(name, args=None, preface=""):
    cid = f"tu_{name}_{time.monotonic_ns()}"
    blocks = ([{"type": "text", "text": preface}] if preface else []) + [
        {"type": "tool_use", "id": cid, "name": name, "input": args or {}}]
    return LLMReply(text=preface, tool_calls=[ToolCall(cid, name, args or {})], blocks=blocks)


class Scripted:
    def __init__(self, replies):
        self.r = list(replies)

    def complete(self, system, messages, tools=None, max_tokens=2048):
        return self.r.pop(0) if self.r else text("(end)")


sre_agent.install_approval_gate()
alert = {"status": "firing",
         "labels": {"alertname": "OdooDown", "severity": "critical"},
         "annotations": {"summary": "Odoo is not answering HTTP health checks",
                         "description": "The probe of http://odoo:8069/web/health has failed for more than 1 minute."},
         "startsAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
ids = sre_agent.handle_alertmanager({"status": "firing", "alerts": [alert]}, run=False)
inc_id = ids[0]
print("incident:", inc_id)


def approver():
    for _ in range(300):
        p = approvals.store.pending()
        if p:
            print("PENDING APPROVAL:", p[0].tool, p[0].args)
            approvals.store.decide(p[0].id, True, "integration-test")
            return
        time.sleep(0.1)


threading.Thread(target=approver, daemon=True).start()
llm = Scripted([
    use("check_container_status", preface="Checking container state first."),
    use("read_logs", {"service": "odoo", "lines": 20}),
    use("query_metrics", {"promql": 'probe_success{job="odoo-health"}'}),
    use("restart_service", {"service": "odoo"},
        preface="The odoo container is exited; restarting it is the smallest safe fix."),
    use("check_container_status"),
    text("## Diagnosis\nThe odoo container was stopped (state exited). High confidence.\n"
         "## Evidence\n- container status: odoo exited\n- probe_success = 0\n"
         "## Proposed fix\nrestart_service(odoo)\n## Result\nOdoo is running again after the restart.\n"),
    text("## Summary\nOdoo stopped and was restarted.\n## Root cause\nContainer was stopped.\n"
         "## Resolution\nRestarted odoo with approval.\n## Prevention\n- Add restart policy alerts\n- Add a runbook\n"),
])
sre_agent.handle_incident(inc_id, llm, approval_timeout=30)
inc = incidents.store.get(inc_id)
print("status:", inc["status"], "| postmortem:", inc["postmortem"])
for e in inc["events"]:
    extra = e.get("tool") or e.get("status") or ""
    print("  ", e["kind"], extra, (e.get("approval_id") or ""))

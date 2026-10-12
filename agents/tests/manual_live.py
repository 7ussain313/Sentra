"""Manual live check: call every tool from Python against the running stack.

Run inside the agents container:  python tests/manual_live.py
Actions use a stand-in approval checker; the real one arrives with the approval flow.
"""
import json
import os
import time

import psycopg2

from app import audit
from app.tools import ApprovalRequired, ToolError, call, set_approval_checker


def show(label, value, limit=300):
    s = json.dumps(value, default=str)
    print(f"[{label}] {s[:limit]}{'...' if len(s) > limit else ''}")


def refused(label, fn):
    try:
        fn()
        print(f"[{label}] FAIL: was allowed")
    except ToolError as e:
        print(f"[{label}] ok refused: {str(e)[:110]}")


INC = "manual-live-check"

print("== read-only tools ==")
show("check_container_status", [
    (c["service"], c["state"], c["health"]) for c in call("check_container_status", incident_id=INC)])
logs = call("read_logs", {"service": "odoo", "lines": 5}, incident_id=INC)
show("read_logs odoo", {"lines": logs["lines"], "tail": logs["text"][-120:]})
logs = call("read_logs", {"service": "db", "lines": 3}, incident_id=INC)
show("read_logs db", {"lines": logs["lines"]})
show("query_metrics", call("query_metrics", {"promql": 'probe_success{job="odoo-health"}'}, incident_id=INC))
show("query_database", call("query_database", {
    "query": "select datname, state, count(*) n from pg_stat_activity group by 1,2 order by 3 desc"},
    incident_id=INC))
show("odoo_search bookings", call("odoo_search", {
    "model": "carwash.booking", "domain": [["state", "=", "done"]],
    "fields": ["name", "price", "state"], "limit": 3}, incident_id=INC))
show("odoo_search unpaid invoices", call("odoo_search", {
    "model": "account.move",
    "domain": [["move_type", "=", "out_invoice"], ["payment_state", "!=", "paid"]],
    "fields": ["name", "amount_total"], "limit": 5}, incident_id=INC))

print("== unsafe inputs ==")
refused("DROP via query_database", lambda: call("query_database", {"query": "DROP TABLE res_partner"}))
refused("stacked SELECT", lambda: call("query_database", {"query": "select 1; select 2"}))
refused("non-allowlisted service", lambda: call("read_logs", {"service": "agents", "lines": 5}))
refused("non-allowlisted model", lambda: call("odoo_search", {"model": "res.users", "fields": ["login"]}))
refused("table read by RO role", lambda: call("query_database", {"query": "select * from res_users limit 1"}))

print("== actions: blocked without approval ==")
for name, args in [("restart_service", {"service": "odoo"}), ("clear_odoo_cache", {}),
                   ("kill_long_running_query", {"pid": 99999})]:
    try:
        call(name, args, incident_id=INC)
        print(f"[{name}] FAIL: ran without approval")
    except ApprovalRequired:
        print(f"[{name}] ok blocked")

print("== actions: approved ==")
set_approval_checker(lambda approval_id, name, args: approval_id == "manual-approval")
show("clear_odoo_cache", call("clear_odoo_cache", {}, incident_id=INC, approval_id="manual-approval"))

# A disposable client session to terminate.
victim = psycopg2.connect(host="db", dbname=os.environ["ODOO_DB_NAME"], user=os.environ["POSTGRES_USER"],
                          password=os.environ["POSTGRES_PASSWORD"], application_name="sentra-test-victim")
vcur = victim.cursor()
vcur.execute("select pg_backend_pid()")
vpid = vcur.fetchone()[0]
show("kill victim pid", call("kill_long_running_query", {"pid": vpid}, incident_id=INC,
                             approval_id="manual-approval"))
try:
    vcur.execute("select 1")
    print("[victim] FAIL: still alive")
except psycopg2.Error:
    print("[victim] ok connection was terminated")

# Refusals inside the SQL helper (approved, but not a legitimate target).
ro = psycopg2.connect(host="db", dbname=os.environ["ODOO_DB_NAME"], user="sentra_readonly",
                      password=os.environ["AGENT_DB_RO_PASSWORD"])
refused("kill our own RO session", lambda: call(
    "kill_long_running_query", {"pid": ro.get_backend_pid()}, approval_id="manual-approval"))
refused("kill a postgres background process", lambda: call(
    "kill_long_running_query", {"pid": 1}, approval_id="manual-approval"))
conn = psycopg2.connect(host="db", dbname=os.environ["ODOO_DB_NAME"], user=os.environ["POSTGRES_USER"],
                        password=os.environ["POSTGRES_PASSWORD"])
cur = conn.cursor()
cur.execute("select pid from pg_stat_activity where backend_type <> 'client backend' limit 1")
bg = cur.fetchone()[0]
refused("kill checkpointer/bgwriter", lambda: call(
    "kill_long_running_query", {"pid": bg}, approval_id="manual-approval"))
conn.close()
ro.close()

if os.environ.get("RESTART_ODOO") == "1":
    print("restarting odoo ...")
    show("restart_service odoo", call("restart_service", {"service": "odoo"}, incident_id=INC,
                                       approval_id="manual-approval"))

print("== audit ==")
entries = [e for e in audit.tail(500) if e.get("incident_id") == INC]
from collections import Counter
print("entries for this run:", len(entries), dict(Counter(e["status"] for e in entries)))
print("last:", {k: entries[-1][k] for k in ("ts", "tool", "status", "approval_id", "duration_ms")})
text = audit.path().read_text()
for var in ("POSTGRES_PASSWORD", "ODOO_AGENT_API_KEY", "AGENT_DB_RO_PASSWORD", "UI_PASSWORD"):
    v = os.environ.get(var, "")
    print(f"secret {var} in audit file:", bool(v) and v in text)

"""Run the SRE agent on the currently firing alert of a failure scenario, with the REAL tools.

    python tests/scenario_agent.py <scenario>

Model: the real Anthropic model when ANTHROPIC_API_KEY is set; otherwise a scripted,
*adaptive* stand-in that reads the real tool results and chooses its next call from
them (so the tools must actually surface the evidence). Approvals are granted
automatically, but only for the actions the scenario expects; any other proposed
action is rejected. Prints one JSON line with the outcome.
"""
import json
import os
import sys
import threading
import time
from typing import Any, Callable, Generator

import httpx

from app import approvals, incidents, sre_agent
from app.config import get_settings
from app.llm import LLMReply, ToolCall

SCENARIOS: dict[str, dict[str, Any]] = {
    "odoo_down": {"alert": "OdooDown", "allow": {"restart_service"}},
    "db_down": {"alert": "OdooDown", "allow": {"restart_service"}},
    "connections_high": {"alert": "PostgresConnectionsHigh", "allow": {"kill_long_running_query"}},
    "blocking_query": {"alert": "OdooHighLatency", "allow": {"kill_long_running_query"}},
    "python_error": {"alert": "OdooDown", "allow": set()},
}


# ------------------------------------------------------------ scripted model
def text(t: str) -> LLMReply:
    return LLMReply(text=t, blocks=[{"type": "text", "text": t}])


def use(name: str, args: dict | None = None, why: str = "") -> LLMReply:
    cid = f"tu_{name}_{time.monotonic_ns()}"
    blocks = ([{"type": "text", "text": why}] if why else []) + [
        {"type": "tool_use", "id": cid, "name": name, "input": args or {}}]
    return LLMReply(text=why, tool_calls=[ToolCall(cid, name, args or {})], blocks=blocks)


def rows(result: Any) -> list[dict]:
    return result.get("rows", []) if isinstance(result, dict) else []


def svc(status: Any, name: str) -> dict:
    return next((c for c in status if isinstance(c, dict) and c.get("service") == name), {})


Plan = Generator[LLMReply, Any, None]


def plan_odoo_down() -> Plan:
    st = yield use("check_container_status", why="Checking the containers first.")
    odoo = svc(st, "odoo")
    if odoo.get("state") == "running":
        yield text("## Diagnosis\nOdoo container is running; no outage found (low confidence).\n"
                   "## Proposed fix\nnone: escalate\n")
        return
    yield use("read_logs", {"service": "odoo", "lines": 40}, why="Reading the last Odoo logs.")
    yield use("query_metrics", {"promql": 'probe_success{job="odoo-health"}'})
    yield use("restart_service", {"service": "odoo"},
              why=f"Odoo is {odoo.get('state')} (exit code {odoo.get('exit_code')}); restarting it.")
    time.sleep(25)
    st2 = yield use("check_container_status", why="Verifying the restart.")
    yield text("## Diagnosis\nThe odoo container was not running "
               f"(state {odoo.get('state')}, exit {odoo.get('exit_code')}). High confidence.\n"
               "## Evidence\n- container status\n- probe_success = 0\n"
               "## Proposed fix\nrestart_service(odoo)\n"
               f"## Result\nOdoo is now {svc(st2, 'odoo').get('state')}.\n")


def plan_db_down() -> Plan:
    st = yield use("check_container_status")
    db = svc(st, "db")
    if db.get("state") == "running":
        yield text("## Diagnosis\nDatabase container is running; cause unclear (low).\n")
        return
    yield use("read_logs", {"service": "db", "lines": 30})
    yield use("restart_service", {"service": "db"},
              why=f"The db container is {db.get('state')}; Odoo cannot serve without it.")
    time.sleep(30)
    st2 = yield use("check_container_status", why="Verifying.")
    yield use("query_metrics", {"promql": "pg_up"})
    yield text("## Diagnosis\nPostgreSQL container was not running "
               f"(state {db.get('state')}). Odoo failed as a consequence. High confidence.\n"
               "## Proposed fix\nrestart_service(db)\n"
               f"## Result\ndb is now {svc(st2, 'db').get('state')}.\n")


def plan_connections() -> Plan:
    yield use("query_metrics", {"promql": "sum(pg_stat_activity_count) / max(pg_settings_max_connections)"})
    q = yield use("query_database", {"query": (
        "select application_name, state, count(*) as n, "
        "max(extract(epoch from now() - state_change))::int as idle_seconds "
        "from pg_stat_activity where backend_type = 'client backend' "
        "group by 1, 2 order by n desc limit 5")})
    top = (rows(q) or [{}])[0]
    culprit = top.get("application_name", "")
    if not culprit or int(top.get("n", 0)) < 10:
        yield text("## Diagnosis\nNo single client holds a large share of connections (low).\n"
                   "## Proposed fix\nnone: escalate\n")
        return
    p = yield use("query_database", {"query": (
        f"select pid from pg_stat_activity where application_name = '{culprit}' "
        "and state like 'idle in transaction%' order by state_change limit 7")})
    pids = [r["pid"] for r in rows(p)]
    for pid in pids:
        yield use("kill_long_running_query", {"pid": pid},
                  why=f"Terminating leaked '{culprit}' session {pid}.")
    time.sleep(20)
    yield use("query_metrics", {"promql": "sum(pg_stat_activity_count) / max(pg_settings_max_connections)"},
              why="Verifying connection usage dropped.")
    yield text(f"## Diagnosis\nClient '{culprit}' holds {top.get('n')} idle-in-transaction "
               "connections and exhausts the pool. High confidence.\n"
               f"## Proposed fix\nTerminated {len(pids)} of its sessions; the owner of that client must fix the leak.\n"
               "## Result\nUsage dropped below the alert threshold.\n")


def plan_blocking() -> Plan:
    yield use("query_metrics", {"promql": 'probe_duration_seconds{job="odoo-login"}'})
    b = yield use("query_database", {"query": (
        "select pid as blocked_pid, pg_blocking_pids(pid) as blockers, wait_event_type, "
        "extract(epoch from now() - query_start)::int as waiting_seconds "
        "from pg_stat_activity where cardinality(pg_blocking_pids(pid)) > 0 limit 10")})
    blockers = sorted({p for r in rows(b) for p in r.get("blockers", [])})
    if not blockers:
        yield text("## Diagnosis\nNo blocked sessions found in pg_stat_activity (low).\n"
                   "## Proposed fix\nnone: escalate\n")
        return
    info = yield use("query_database", {"query": (
        "select pid, application_name, state, extract(epoch from now() - xact_start)::int as xact_age_s "
        f"from pg_stat_activity where pid = {int(blockers[0])}")})
    who = (rows(info) or [{}])[0]
    yield use("kill_long_running_query", {"pid": int(blockers[0])},
              why=f"Session {blockers[0]} ('{who.get('application_name')}') is blocking {len(rows(b))} "
                  f"others and has been in a transaction for {who.get('xact_age_s')}s.")
    time.sleep(20)
    yield use("query_metrics", {"promql": 'probe_success{job="odoo-login"}'}, why="Verifying.")
    yield text("## Diagnosis\nA long-held lock by "
               f"'{who.get('application_name')}' (pid {blockers[0]}) blocked Odoo's queries. High confidence.\n"
               "## Proposed fix\nTerminate the blocking session.\n## Result\nLogin page responds again.\n")


def plan_python_error() -> Plan:
    st = yield use("check_container_status")
    logs = yield use("read_logs", {"service": "odoo", "lines": 120}, why="Looking for tracebacks.")
    body = logs.get("text", "") if isinstance(logs, dict) else str(logs)
    err = [ln for ln in body.splitlines() if "Error" in ln and "File " not in ln]
    last = err[-1].split(" ", 1)[-1][-200:] if err else "unknown"
    yield text(
        "## Diagnosis\nOdoo is running but fails to load the registry because of a Python error in a "
        f"custom module: `{last}`. High confidence (traceback in logs).\n"
        f"## Evidence\n- odoo container state: {svc(st, 'odoo').get('state')}\n- Traceback in Odoo logs\n"
        "## Proposed fix\nnone: escalate. A restart cannot fix a code error; a developer must fix or "
        "revert the module change.\n")


PLANS: dict[str, Callable[[], Plan]] = {
    "odoo_down": plan_odoo_down, "db_down": plan_db_down, "connections_high": plan_connections,
    "blocking_query": plan_blocking, "python_error": plan_python_error,
}


class AdaptiveScripted:
    def __init__(self, plan: Plan) -> None:
        self.plan, self.started, self.done = plan, False, False

    def complete(self, system, messages, tools=None, max_tokens=2048):
        if tools is None or self.done:  # final-report / postmortem narrative calls
            return text("## Summary\nScenario run.\n## Root cause\nSee diagnosis.\n## Resolution\n"
                        "See actions taken.\n## Prevention\n- Review alert thresholds and runbooks.\n")
        try:
            if not self.started:
                self.started = True
                return next(self.plan)
            last = messages[-1]["content"]
            res = last[0]["content"] if isinstance(last, list) else ""
            try:
                value = json.loads(res.split("\n\nNOTE:")[0])
            except ValueError:
                value = {"error": res}
            return self.plan.send(value)
        except StopIteration:
            self.done = True
            return text("## Diagnosis\n(plan ended)\n")


# -------------------------------------------------------------------- main
def firing_alert(name: str) -> dict:
    url = get_settings().prometheus_url + "/api/v1/alerts"
    for a in httpx.get(url, timeout=10).json()["data"]["alerts"]:
        if a["labels"].get("alertname") == name and a["state"] == "firing":
            return {"status": "firing", "labels": a["labels"], "annotations": a["annotations"],
                    "startsAt": a["activeAt"]}
    return {"status": "firing", "labels": {"alertname": name, "severity": "unknown"},
            "annotations": {"summary": name, "description": "(alert not firing in Prometheus at run time)"}}


def main() -> None:
    scenario = sys.argv[1]
    cfg = SCENARIOS[scenario]
    sre_agent.install_approval_gate()
    inc = incidents.store.create(cfg["alert"], firing_alert(cfg["alert"]))
    cfg_s = get_settings()
    real = bool(cfg_s.llm_api_key if cfg_s.llm_provider == "openai_compat" else cfg_s.anthropic_api_key)
    llm = None if real else AdaptiveScripted(PLANS[scenario]())

    decided: list[dict] = []
    stop = threading.Event()

    def approver() -> None:
        seen: set[str] = set()
        while not stop.is_set():
            for a in approvals.store.pending():
                if a.id in seen:
                    continue
                seen.add(a.id)
                ok = a.tool in cfg["allow"]
                approvals.store.decide(a.id, ok, "scenario-runner")
                decided.append({"tool": a.tool, "args": a.args, "approved": ok})
            time.sleep(0.2)

    threading.Thread(target=approver, daemon=True).start()
    started = time.time()
    sre_agent.handle_incident(inc["id"], llm, approval_timeout=90)
    stop.set()
    final = incidents.store.get(inc["id"])
    tool_calls = [e for e in final["events"] if e["kind"] == "tool_call"]
    print("RESULT " + json.dumps({
        "scenario": scenario, "incident": inc["id"], "status": final["status"],
        "model": f"{cfg_s.llm_provider}:{cfg_s.llm_model}" if real else "scripted-adaptive (no API key)",
        "agent_seconds": round(time.time() - started, 1),
        "tools": [t["tool"] + ":" + t["status"] for t in tool_calls],
        "actions": decided, "postmortem": final.get("postmortem"),
        "diagnosis": (final.get("diagnosis") or "")[:600],
    }))


if __name__ == "__main__":
    main()

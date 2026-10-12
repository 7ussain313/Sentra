#!/usr/bin/env python3
"""Break the stack on purpose and record how the alerting + SRE agent chain copes.

    python scripts/failure_scenarios.py [scenario ...]     # default: all five

Per scenario it records: when the alert fired in Prometheus, when the agent service
received it, the agent's diagnosis and actions (approved automatically, but only for the
expected action), and time to recovery. Results go to incidents/FAILURE_SCENARIOS.md.

The agent run uses the real Anthropic model if ANTHROPIC_API_KEY is configured, otherwise
a scripted adaptive stand-in that still drives the REAL tools (see agents/tests/scenario_agent.py).
Requires the stack to be up and healthy. Takes roughly 3-6 minutes per scenario.
"""
import base64
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVICE_FILE = ROOT / "odoo" / "addons" / "carwash" / "models" / "service.py"
OUT_MD = ROOT / "incidents" / "FAILURE_SCENARIOS.md"
OUT_JSON = ROOT / "incidents" / "failure_scenarios.json"


def load_env() -> dict[str, str]:
    env = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


ENV = load_env()
AUTH = "Basic " + base64.b64encode(f"{ENV['UI_USERNAME']}:{ENV['UI_PASSWORD']}".encode()).decode()


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def dc(*args: str, check: bool = True, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, capture_output=True, text=True,
                          timeout=timeout, check=check)


def http(url: str, headers: dict | None = None, timeout: int = 15) -> tuple[int, str, float]:
    t0 = time.time()
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace"), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, "", time.time() - t0
    except Exception:
        return 0, "", time.time() - t0


def prom(query: str) -> list[dict]:
    from urllib.parse import quote
    code, body, _ = http("http://localhost:9090/api/v1/query?query=" + quote(query))
    return json.loads(body)["data"]["result"] if code == 200 else []


def prom_value(query: str) -> float | None:
    r = prom(query)
    return float(r[0]["value"][1]) if r else None


def firing_alerts() -> set[str]:
    code, body, _ = http("http://localhost:9090/api/v1/alerts")
    if code != 200:
        return set()
    return {a["labels"]["alertname"] for a in json.loads(body)["data"]["alerts"] if a["state"] == "firing"}


def agent_alerts() -> list[dict]:
    code, body, _ = http("http://localhost:8000/alerts", {"Authorization": AUTH})
    return json.loads(body) if code == 200 else []


def odoo_ok() -> bool:
    code, _, took = http("http://localhost:8069/web/login", timeout=20)
    return code == 200 and took < 2.0


def wait_for(cond, timeout: float, interval: float = 3.0) -> float | None:
    start = time.time()
    while time.time() - start < timeout:
        try:
            if cond():
                return time.time() - start
        except Exception:
            pass
        time.sleep(interval)
    return None


def baseline() -> None:
    log("waiting for a healthy baseline (no firing alerts, Odoo OK)")
    ok = wait_for(lambda: odoo_ok() and not firing_alerts() and
                  prom_value('probe_success{job="odoo-login"}') == 1.0, 480)
    if ok is None:
        raise SystemExit("stack is not healthy; fix it before running scenarios")


# ---------------------------------------------------------------- injections
def inject_odoo_down() -> None:
    dc("stop", "odoo")


def inject_db_down() -> None:
    dc("stop", "db")


def inject_connections() -> None:
    maxc = int(prom_value("max(pg_settings_max_connections)") or 100)
    current = int(prom_value("sum(pg_stat_activity_count)") or 10)
    n = int(maxc * 0.86) - current
    log(f"filling PostgreSQL: {current} in use + {n} leaked sessions of {maxc}")
    dc("exec", "-d", "-T", "agents", "python", "/app/tests/scenario_inject.py", "fill", str(n))


def inject_lock() -> None:
    dc("exec", "-d", "-T", "agents", "python", "/app/tests/scenario_inject.py", "lock")


def inject_python_error() -> None:
    original = SERVICE_FILE.read_bytes()  # bytes in/out: never rewrite line endings
    (ROOT / "scripts" / ".service.py.bak").write_bytes(original)
    SERVICE_FILE.write_bytes(
        b'raise RuntimeError("scenario: simulated Python error in custom module")\n' + original)
    dc("restart", "odoo")


def cleanup_python_error() -> None:
    bak = ROOT / "scripts" / ".service.py.bak"
    if bak.exists():
        SERVICE_FILE.write_bytes(bak.read_bytes())
        bak.unlink()
    dc("restart", "odoo")


def cleanup_injectors() -> None:
    # The slim image has no pkill; the injector script can terminate its siblings itself.
    dc("exec", "-T", "agents", "python", "/app/tests/scenario_inject.py", "kill", check=False)


SCENARIOS = {
    "odoo_down": dict(title="Odoo container stopped", alert="OdooDown", inject=inject_odoo_down,
                      cleanup=lambda: dc("start", "odoo", check=False),
                      recovered=lambda: odoo_ok(), expect_action="restart_service"),
    "db_down": dict(title="PostgreSQL container stopped", alert="OdooDown", inject=inject_db_down,
                    cleanup=lambda: dc("start", "db", check=False),
                    recovered=lambda: odoo_ok(), expect_action="restart_service"),
    "connections_high": dict(title="PostgreSQL connections nearly exhausted (leaked sessions)",
                             alert="PostgresConnectionsHigh", inject=inject_connections,
                             cleanup=cleanup_injectors,
                             recovered=lambda: (prom_value("sum(pg_stat_activity_count) / "
                                                           "max(pg_settings_max_connections)") or 1) < 0.8,
                             expect_action="kill_long_running_query"),
    "blocking_query": dict(title="Long-held lock blocks Odoo's queries", alert="OdooHighLatency",
                           inject=inject_lock, cleanup=cleanup_injectors,
                           recovered=lambda: odoo_ok(), expect_action="kill_long_running_query"),
    "python_error": dict(title="Python error in the custom module", alert="OdooDown",
                         inject=inject_python_error, cleanup=cleanup_python_error,
                         recovered=lambda: odoo_ok(), expect_action=None, manual_recovery=True),
}


# ------------------------------------------------------------------ runner
def run_scenario(name: str) -> dict:
    sc = SCENARIOS[name]
    log(f"=== {name}: {sc['title']} ===")
    baseline()
    before = len(agent_alerts())
    res: dict = {"scenario": name, "title": sc["title"], "expected_alert": sc["alert"],
                 "started": datetime.now(timezone.utc).isoformat()}
    t0 = time.time()
    try:
        sc["inject"]()
        log("failure injected; waiting for the alert to fire in Prometheus")
        t = wait_for(lambda: sc["alert"] in firing_alerts(), 420)
        res["alert_fired_s"] = round(time.time() - t0) if t is not None else None
        log(f"alert {sc['alert']} firing after {res['alert_fired_s']}s" if t is not None
            else "alert never fired")

        def received() -> bool:
            return any(a["status"] == "firing" and sc["alert"] in a["alertnames"]
                       for a in agent_alerts()[:max(len(agent_alerts()) - before, 0)])

        t = wait_for(received, 180)
        res["agent_received_s"] = round(time.time() - t0) if t is not None else None
        log(f"agent service received the alert at {res['agent_received_s']}s")

        log("running the SRE agent on the incident")
        out = dc("exec", "-T", "-w", "/app", "-e", "PYTHONPATH=/app", "-e", "MAX_STEPS=14",
                 "agents", "python", "tests/scenario_agent.py", name, timeout=900)
        line = next((ln for ln in out.stdout.splitlines() if ln.startswith("RESULT ")), None)
        if line is None:
            res["agent_error"] = (out.stdout + out.stderr)[-800:]
            log("agent run produced no result:\n" + res["agent_error"])
        else:
            res["agent"] = json.loads(line[7:])
            log(f"agent: {res['agent']['status']} | tools {res['agent']['tools']} | actions {res['agent']['actions']}")
        res["agent_done_s"] = round(time.time() - t0)

        if sc.get("manual_recovery"):
            log("no automated fix exists; recovering manually (revert + restart)")
            sc["cleanup"]()
            res["manual_recovery"] = True
        t = wait_for(sc["recovered"], 300)
        res["recovered_s"] = round(time.time() - t0) if t is not None else None
        log(f"recovered after {res['recovered_s']}s" if t is not None else "NOT recovered in time")
    finally:
        if not sc.get("manual_recovery"):
            sc["cleanup"]()
        else:
            bak = ROOT / "scripts" / ".service.py.bak"
            if bak.exists():
                cleanup_python_error()
    t = wait_for(lambda: any(a["status"] == "resolved" and sc["alert"] in a["alertnames"]
                             for a in agent_alerts()[:max(len(agent_alerts()) - before, 0)]), 420)
    res["resolved_notice_s"] = round(time.time() - t0) if t is not None else None
    log(f"resolved notice at {res['resolved_notice_s']}s")
    return res


def verdict(r: dict) -> str:
    a = r.get("agent")
    if not a:
        return "agent did not run"
    exp = SCENARIOS[r["scenario"]]["expect_action"]
    acted = [x for x in a["actions"] if x["approved"]]
    if exp is None:
        ok = not a["actions"] and a["status"] in ("diagnosed", "escalated")
    else:
        ok = any(x["tool"] == exp for x in acted) and a["status"] == "fixed"
    return ("PASS" if ok and r.get("recovered_s") else "FAIL")


def write_report(results: list[dict]) -> None:
    OUT_JSON.write_text(json.dumps(results, indent=2), encoding="utf-8")
    model = next((r["agent"]["model"] for r in results if r.get("agent")), "n/a")
    lines = [
        "# Failure scenario results",
        "",
        f"Run: {datetime.now():%Y-%m-%d %H:%M}. Agent model: **{model}**.",
        "",
        "Failures are injected into the live stack. The alert chain (Prometheus -> Alertmanager -> "
        "agent webhook) and the tools are real. "
        + ("The reasoning step used a scripted adaptive stand-in because no `ANTHROPIC_API_KEY` was "
           "configured: it reads the real tool output to choose its next call, so it validates that "
           "the evidence is available and the actions work, **not** the quality of a real model's "
           "diagnosis. Re-run with a key to evaluate the model."
           if "scripted" in model else "The reasoning step used the real model."),
        "",
        "| Scenario | Alert | Alert fired | Agent got it | Agent action | Recovered | Result |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        a = r.get("agent") or {}
        acts = ", ".join(f"{x['tool']}({json.dumps(x['args'])})" + ("" if x["approved"] else " [rejected]")
                         for x in a.get("actions", [])) or "none"
        fmt = lambda v: f"{v}s" if v is not None else "n/a"  # noqa: E731
        rec = fmt(r.get("recovered_s")) + (" (manual)" if r.get("manual_recovery") else "")
        lines.append(f"| {r['title']} | {r['expected_alert']} | {fmt(r.get('alert_fired_s'))} | "
                     f"{fmt(r.get('agent_received_s'))} | {acts} | {rec} | **{verdict(r)}** |")
    lines += ["", "Times are seconds from the moment the failure was injected.", ""]
    for r in results:
        a = r.get("agent") or {}
        lines += [f"## {r['title']}", "",
                  f"- Alert: `{r['expected_alert']}`; fired after {r.get('alert_fired_s')}s, "
                  f"reached the agent after {r.get('agent_received_s')}s.",
                  f"- Incident: `{a.get('incident', 'n/a')}` (postmortem `incidents/{a.get('postmortem', 'n/a')}`), "
                  f"status **{a.get('status', 'n/a')}**.",
                  f"- Tools used: {', '.join(a.get('tools', [])) or 'none'}.",
                  f"- Recovery: {r.get('recovered_s')}s" + (" via manual revert + restart (no safe automated fix)."
                                                            if r.get("manual_recovery") else "."),
                  "", "Diagnosis:", "", "> " + (a.get("diagnosis", "n/a").replace("\n", "\n> ")), ""]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    names = sys.argv[1:] or list(SCENARIOS)
    cid = dc("ps", "-q", "agents").stdout.strip()
    subprocess.run(["docker", "cp", str(ROOT / "agents" / "tests") + "/.", f"{cid}:/app/tests/"], check=True)
    results = []
    for n in names:
        try:
            results.append(run_scenario(n))
        except SystemExit:
            raise
        except Exception as e:  # keep going; the report shows what happened
            log(f"scenario {n} crashed: {e!r}")
            results.append({"scenario": n, "title": SCENARIOS[n]["title"],
                            "expected_alert": SCENARIOS[n]["alert"], "crash": repr(e)})
            cleanup_injectors()
            SCENARIOS[n]["cleanup"]()
        write_report(results)
    log("done: " + ", ".join(f"{r['scenario']}={verdict(r) if 'crash' not in r else 'CRASH'}" for r in results))


if __name__ == "__main__":
    main()

"""Failure injectors that run inside the agents container (detached by the orchestrator).

    python tests/scenario_inject.py fill <n>   # n sessions held idle-in-transaction by 'leaky-client'
    python tests/scenario_inject.py lock       # ACCESS EXCLUSIVE lock on res_users held by 'nightly-report-job'

They connect as Odoo's own database role, like a real misbehaving client would, and
exit when their sessions are terminated (which is what the agent's fix does).
"""
import os
import sys
import time

import psycopg2


def connect(app: str):
    return psycopg2.connect(host="db", dbname=os.environ["ODOO_DB_NAME"], user=os.environ["POSTGRES_USER"],
                            password=os.environ["POSTGRES_PASSWORD"], application_name=app)


def alive(conn) -> bool:
    try:
        conn.cursor().execute("select 1")
        return True
    except psycopg2.Error:
        return False


def main() -> None:
    mode = sys.argv[1]
    hold_seconds = 1500
    if mode == "fill":
        conns = []
        for _ in range(int(sys.argv[2])):
            c = connect("leaky-client")
            c.cursor().execute("select 1")  # opens a transaction and leaves it idle
            conns.append(c)
        print(f"holding {len(conns)} idle-in-transaction connections", flush=True)
        deadline = time.time() + hold_seconds
        while time.time() < deadline and any(alive(c) for c in conns):
            time.sleep(2)
            conns = [c for c in conns if not c.closed]
    elif mode == "lock":
        c = connect("nightly-report-job")
        c.cursor().execute("LOCK TABLE res_users IN ACCESS EXCLUSIVE MODE")
        print("holding ACCESS EXCLUSIVE lock on res_users", flush=True)
        deadline = time.time() + hold_seconds
        while time.time() < deadline and alive(c):
            time.sleep(2)
    elif mode == "kill":  # terminate other running injectors (cleanup)
        import signal
        for pid in os.listdir("/proc"):
            if not pid.isdigit() or int(pid) == os.getpid():
                continue
            try:
                cmd = open(f"/proc/{pid}/cmdline").read()
            except OSError:
                continue
            if "scenario_inject.py" in cmd:
                os.kill(int(pid), signal.SIGTERM)
        print("injectors terminated", flush=True)
    else:
        raise SystemExit("unknown mode")
    print("injector finished", flush=True)


if __name__ == "__main__":
    main()

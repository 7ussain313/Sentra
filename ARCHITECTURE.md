# Sentra — Architecture

See `SYSTEM_DESIGN.md` for scope, domain model, and incident types.

---

## 1. Folder Structure

```
Sentra/
├── docker-compose.yml
├── .env.example            # committed
├── .env                    # never committed
├── .gitignore
├── README.md
├── SYSTEM_DESIGN.md
├── ARCHITECTURE.md
├── todo.md
├── odoo/
│   ├── odoo.conf
│   └── addons/
│       └── carwash/        # custom module (models, views, security, data, tests)
├── agents/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py         # FastAPI: /health, /webhook/alertmanager, /ui, /api
│   │   ├── auth.py         # HTTP Basic auth for UI and API
│   │   ├── ui/             # static web UI (incidents, approvals, ask)
│   │   ├── config.py       # env settings
│   │   ├── llm.py          # LLM client wrapper
│   │   ├── loop.py         # reasoning loop
│   │   ├── sre_agent.py    # SRE prompt + incident flow
│   │   ├── business_agent.py
│   │   ├── approvals.py    # pending-approval store
│   │   ├── audit.py        # audit log writer
│   │   ├── postmortem.py
│   │   └── tools/
│   │       ├── registry.py # tool schemas + read/action classification
│   │       ├── logs.py
│   │       ├── containers.py
│   │       ├── metrics.py
│   │       ├── database.py
│   │       ├── odoo.py
│   │       └── actions.py
│   └── tests/
├── monitoring/
│   ├── prometheus/prometheus.yml
│   ├── prometheus/alerts.yml
│   ├── alertmanager/alertmanager.yml
│   ├── blackbox/blackbox.yml
│   └── grafana/{provisioning,dashboards}/
├── incidents/              # generated postmortems (Markdown)
├── audit/                  # audit log (JSONL), gitignored
└── scripts/                # seed loading, failure-injection helpers
```

---

## 2. Docker Compose Services

All services share one network, `sentra_net`.

| Service | Image / build | Port (host) | Depends on | Notes |
|---------|---------------|-------------|------------|-------|
| `db` | postgres:15 | — | — | Volume `pgdata` |
| `odoo` | odoo:17 | 8069 | db | Mounts `odoo/addons`, `odoo.conf`, volume `odoo-data` |
| `agents` | `./agents` | 8000 | odoo, prometheus | Docker socket mounted; audit + incidents volumes |
| `prometheus` | prom/prometheus | 9090 | — | Loads `alerts.yml` |
| `alertmanager` | prom/alertmanager | 9093 | prometheus | Webhook to `agents` |
| `blackbox` | prom/blackbox-exporter | — | — | Probes `odoo:8069` |
| `postgres_exporter` | prometheuscommunity/postgres-exporter | — | db | |
| `cadvisor` | gcr.io/cadvisor/cadvisor | — | — | Host/cgroup metrics; per-container series only where cAdvisor can identify containers (Linux) |
| `grafana` | grafana/grafana | 3000 | prometheus | Provisioned datasource + dashboards |

Container metrics with real names come from the `agents` service (`GET /metrics`, Docker socket, Basic auth, scraped as job `containers`), because cAdvisor cannot resolve container names on every host (for example Docker Desktop with the containerd image store). The `ContainerMemoryHigh` alert and the container dashboard use it. `postgres_exporter` connects as the least-privilege `sentra_monitor` role (`pg_monitor`), created by `scripts/create_monitor_role.sh`. Prometheus and Alertmanager are bound to `127.0.0.1` only.

The web UI is served by the `agents` service at `http://localhost:8000/ui`. Only Odoo, Grafana, and the agent service (UI + `/health`) are exposed to the host; the rest are internal.

---

## 3. Alert Flow

```
blackbox / postgres_exporter / cAdvisor
            │ scrape
            ▼
       Prometheus ──(alerts.yml rules)──> Alertmanager
                                              │ webhook POST
                                              ▼
                              agents: /webhook/alertmanager
                                              │ dedupe + start incident
                                              ▼
                                        SRE agent loop
                                              │
                                              ▼
                                  Web UI (incident feed)
```

Alerts: `OdooDown`, `OdooHighLatency`, `PostgresConnectionsHigh`, `ContainerMemoryHigh`.

* `OdooDown`: the `/web/health` probe fails (container down, HTTP 500s from a Python error in a module) **or** `pg_up == 0` (Odoo's health endpoint still answers 200 when PostgreSQL is gone).
* `OdooHighLatency`: the login page takes more than 2 s, **or** it fails while `/web/health` is still up (blocked database).
* `PostgresConnectionsHigh`: more than 80% of `max_connections` in use.
* `ContainerMemoryHigh`: working set above 1.5 GiB for any Sentra container.
Alertmanager groups by `alertname`, repeats every 30 minutes while firing, and also sends `resolved` notices.

---

## 4. Agent Tool Layer

### 4.1 Tools

| Tool | Class | Input | Output |
|------|-------|-------|--------|
| `read_logs` | read-only | `service` (allowlist), `lines` (1–500) | last N log lines (text) |
| `check_container_status` | read-only | — | list of `{name, state, health, restarts, uptime}` |
| `query_metrics` | read-only | `promql` (string) | Prometheus result JSON (truncated) |
| `query_database` | read-only | `query` (single SELECT) | rows (max 100) as JSON |
| `odoo_search` | read-only | `model` (allowlist), `domain`, `fields`, `limit` | list of records |
| `restart_service` | **action** | `service` (allowlist) | success flag + new container state |
| `clear_odoo_cache` | **action** | — | success flag |
| `kill_long_running_query` | **action** | `pid` (int) | success flag |

### 4.2 Safety rules (enforced in code, not in the prompt)
* **Allowlists:** services (`odoo`, `db`), Odoo models (`carwash.*`, `res.partner`, `account.move`).
* **Input validation:** typed schemas; reject unknown fields and out-of-range values.
* **SQL guard:** exactly one statement, must begin with `SELECT`, no `;` chaining, no writing functions; executed in a read-only transaction by a read-only DB role.
* **Output limits:** logs and rows are truncated to keep the context small.
* **Action gate:** the registry marks action tools. `registry.call()` runs an action only when called with an `approval_id` that the installed approval checker grants for that exact tool and arguments; the default checker denies everything, so nothing can run before the approval flow is wired in.
* **Audit:** every call, input, output (truncated), timestamp, incident ID, and approval decision is appended to `audit/audit.jsonl`.

### 4.3 Credentials
* **Odoo:** dedicated user `sentra_agent`, read-only access, authenticated through the external API with an API key from `.env`. The Business agent uses only this user.
* **PostgreSQL** (created by `scripts/create_agent_db_roles.sh`):
  * `sentra_readonly` has `pg_monitor` only, read-only transactions and a 5 s timeout. It can read `pg_stat_*`, locks and catalogs but no table data. Used by `query_database`.
  * `sentra_signal` has no table access. It may only `EXECUTE` two `SECURITY DEFINER` helpers: `sentra_terminate_backend(pid)` (client backends of the Odoo database only; refuses its own session, background processes and the agent roles) and `sentra_clear_odoo_cache()` (bumps Odoo's `base_cache_signaling_*` sequences so every worker drops its caches). A plain `pg_signal_backend` role could not be used because Odoo connects as the cluster superuser, which that role cannot signal. Used by the approval-gated action tools.
* **Docker:** socket access limited to the tools in `containers.py`/`actions.py`, and only for allowlisted services.

---

## 5. Agent Reasoning Loop

```
messages = [system_prompt, alert_context]
for step in 1..MAX_STEPS (default 8):
    reply = llm(messages, tools)
    if reply has no tool calls:
        return reply  # diagnosis + proposed fix
    for call in reply.tool_calls:
        validate(call)
        if call.tool is action:
            decision = approvals.request(call)     # blocks, with timeout
            if decision != approved: result = "rejected / timed out"
            else: result = run(call)
        else:
            result = run(call)
        audit(call, result)
        messages += [call, result]
return "step limit reached" + evidence so far
```

**Stop conditions:** the model returns a final answer; `MAX_STEPS` reached; an action is rejected or times out (agent reports and stops); LLM or tool failure that cannot be retried.
After an approved action, the agent runs one verification pass (status + metrics) before concluding.

---

## 6. Human-Approval Flow (Web UI)

**Web UI pages** (static HTML + JS served from `agents/app/ui/`, talking to `/api`):
* **Incidents**: live list and detail view (alert, agent steps, diagnosis, proposed fix, postmortem link). Updates by polling every 3 s.
* **Approvals**: pending actions with **Approve** / **Reject** buttons.
* **Ask**: a text box for the Business agent.
* **Audit**: recent tool calls and decisions.

**Flow**
1. Agent decides an action tool is needed; `approvals.request()` stores `{id, tool, args, incident_id, expires_at}` and the incident shows "awaiting approval".
2. The UI displays the exact action and arguments with Approve / Reject.
3. `POST /api/approvals/{id}` is authenticated (HTTP Basic, `UI_USERNAME` / `UI_PASSWORD`) and single-use.
4. The decision resolves the waiting agent.
5. No answer within `APPROVAL_TIMEOUT` (default 10 min) cancels the action and logs `timeout`.
6. Decision, user, and time are written to the audit log.

Business-agent flow: Ask page → `POST /api/ask` → Business agent loop (read-only tools only) → answer rendered in the page.

Security: the UI is bound to localhost by default; every `/ui` and `/api` route except `/health` and the Alertmanager webhook requires Basic auth. The webhook accepts requests only from the internal Docker network.

---

## 7. Secrets Management
* All secrets live in `.env` (UI username/password, LLM API key, Odoo API key, DB passwords, Grafana admin password).
* `.env` is in `.gitignore`; `.env.example` lists variable names with placeholder values.
* Compose injects values through `env_file`; secrets never appear in images, logs, or prompts.
* The audit logger redacts known secret values.

---

## 8. Testing Strategy

| Layer | Approach |
|-------|----------|
| Odoo module | Odoo `TransactionCase` tests: state transitions, invoice generation, access rights, constraints. |
| Tools | pytest unit tests per tool, including rejected unsafe inputs (non-SELECT SQL, non-allowlisted service). |
| Agent loop | pytest with a mocked LLM returning scripted tool calls; assert step limit, approval gating, audit entries. |
| Approval flow | Test timeout, reject, and approve paths through the `/api/approvals` endpoints. |
| End-to-end | Failure scenarios run by hand or script: stop Odoo, stop DB, fill connections, long query, Python error. Results recorded in `incidents/`. |

---

## 9. Development Order

1. Infrastructure: Compose, Postgres, Odoo, repo (Phase 1)
2. Odoo models, then logic, views, security (Phases 2–3)
3. Seed data (Phase 4)
4. Monitoring and alerts (Phase 5)
5. Agent tool layer with audit log (Phase 6)
6. SRE agent loop and postmortems (Phase 7)
7. Web UI (incident feed) and approval flow (Phase 8)
8. Business agent (Phase 9)
9. Tests and failure scenarios (Phase 10)
10. Docs and demo (Phase 11)

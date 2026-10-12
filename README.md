# Sentra

An AI SRE platform for Odoo, demonstrated on a car wash business.

> Work in progress. See `SYSTEM_DESIGN.md`, `ARCHITECTURE.md`, and `todo.md`.

## Quick start

```bash
cp .env.example .env   # fill in values
docker compose up --build
```

- Odoo: http://localhost:8069
- Web UI (login with `UI_USERNAME` / `UI_PASSWORD`): http://localhost:8000/ui
- Agent service health: http://localhost:8000/health

## Seed demo data

After the `carwash` module is installed in the `sentra` database:

```bash
docker compose cp scripts/seed.py odoo:/tmp/seed.py
docker compose exec -T odoo sh -c 'odoo shell -c /tmp/odoo.conf -d sentra --no-http \
  --db_host "$HOST" --db_user "$USER" --db_password "$PASSWORD" < /tmp/seed.py'
```

The script is idempotent. Passwords for the `manager`, `staff` and `sentra_agent`
users and the agent's API key are generated and printed **once** on first run;
store them in `.env` (`SEED_*_PASSWORD`, `ODOO_AGENT_API_KEY`).

## Monitoring

```bash
sh scripts/create_monitor_role.sh   # one-time: least-privilege role for postgres_exporter
docker compose up -d
```

| URL | What |
|-----|------|
| http://localhost:3000 | Grafana (`admin` / `GRAFANA_ADMIN_PASSWORD`), dashboards in the *Sentra* folder |
| http://localhost:9090 | Prometheus (localhost only) |
| http://localhost:9093 | Alertmanager (localhost only) |

Alerts (`OdooDown`, `OdooHighLatency`, `PostgresConnectionsHigh`, `ContainerMemoryHigh`)
are posted by Alertmanager to `POST /webhook/alertmanager` on the agent service.
Received alerts are listed at `GET /alerts` and appended to `audit/alerts.jsonl`.

## Agent tool layer

```bash
sh scripts/create_agent_db_roles.sh     # one-time: sentra_readonly / sentra_signal + helper functions
docker compose exec -T -e PYTHONPATH=/app -w /app agents python tests/manual_live.py   # live check
```

Tools live in `agents/app/tools/`; every call goes through `registry.call()`, which validates
input, gates action tools behind an approval and appends to `audit/audit.jsonl`.
Offline safety tests: `pip install -r agents/requirements-dev.txt && pytest agents/tests`.

## SRE agent

Set `ANTHROPIC_API_KEY` (and optionally `LLM_MODEL`, `MAX_STEPS`, `APPROVAL_TIMEOUT_SECONDS`) in `.env`.
An Alertmanager alert starts an incident (deduplicated by alert name over 10 minutes); the agent
investigates with read-only tools, proposes a fix, waits for human approval before any action,
verifies, and writes a postmortem to `incidents/<id>.md`.

| Endpoint | Purpose |
|----------|---------|
| `GET /api/incidents`, `GET /api/incidents/{id}` | incident list / detail with agent steps |
| `GET /api/incidents/{id}/postmortem` | postmortem Markdown |
| `GET /api/approvals`, `POST /api/approvals/{id}` `{"approve": true}` | pending approvals / decide (single use) |

Without an API key the incident is still recorded and a postmortem is written, with status `agent_unavailable`.

## Web UI and business agent

`http://localhost:8000/ui` (HTTP Basic auth with `UI_USERNAME` / `UI_PASSWORD`):
**Incidents** (live list, agent steps, diagnosis, proposed fix, postmortem, Approve/Reject),
**Approvals**, **Ask** (business agent, read-only) and **Audit**.

The business agent only has `odoo_search` and `odoo_aggregate`, which use the read-only
`sentra_agent` API user with fixed RPC methods (`search_read`, `read_group`); Odoo itself
rejects any write from that user. `agents/tests/manual_business_truth.py` checks the five
supported questions' queries against SQL ground truth.

## Testing and failure scenarios

| Suite | How to run | Count |
|-------|-----------|-------|
| Odoo module (state machine, invoicing, access rights, constraints) | create a scratch DB, then `odoo -d <db> -i carwash --test-enable --test-tags /carwash --stop-after-init` inside the `odoo` container | 26 |
| Agent service (tools, safety rules, loop with a scripted LLM, approval API, UI, business agent) | `pip install -r agents/requirements-dev.txt && pytest agents/tests` (or run inside the `agents` container) | 94 |
| Live data check for the business questions | `python tests/manual_business_truth.py` in the `agents` container | 5 questions + write denial |
| Failure scenarios (break the live stack on purpose) | `python scripts/failure_scenarios.py [scenario ...]` | 5 scenarios |

`scripts/failure_scenarios.py` stops Odoo, stops PostgreSQL, leaks connections, holds a blocking lock,
and breaks the custom module; for each it records alert time, agent diagnosis and action, and time to
recovery in `incidents/FAILURE_SCENARIOS.md`. Without an `ANTHROPIC_API_KEY` the reasoning step is a
scripted stand-in that drives the real tools, which validates alerts, evidence and actions but not a
real model's judgement; with a key set the same harness runs the real model.

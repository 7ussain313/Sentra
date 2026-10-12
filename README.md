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

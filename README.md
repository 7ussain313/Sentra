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

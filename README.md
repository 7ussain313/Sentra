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

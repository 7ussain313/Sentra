#!/bin/sh
# Create (or update) the least-privilege PostgreSQL role used by postgres_exporter.
# Idempotent. Run from the repo root after `docker compose up -d db`:
#   sh scripts/create_monitor_role.sh
set -eu
set -a; . ./.env; set +a
docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sentra_monitor') THEN
    CREATE ROLE sentra_monitor LOGIN;
  END IF;
END
\$\$;
ALTER ROLE sentra_monitor WITH PASSWORD '${MONITOR_DB_PASSWORD}';
GRANT pg_monitor TO sentra_monitor;
SQL
echo "sentra_monitor role ready"

#!/bin/sh
# Least-privilege PostgreSQL access for the agent tool layer. Idempotent.
# Run from the repo root after Odoo's database exists:
#   sh scripts/create_agent_db_roles.sh
#
#   sentra_readonly  pg_monitor only: can read pg_stat_*/pg_locks/catalogs, no table data,
#                    read-only transactions, 5s statement timeout. Used by query_database.
#   sentra_signal    no table access at all; may only EXECUTE two SECURITY DEFINER helpers
#                    that terminate a client backend of the Odoo DB or bump Odoo's cache
#                    signalling sequences. Used by the approved action tools.
set -eu
set -a; . ./.env; set +a
: "${AGENT_DB_RO_PASSWORD:?missing in .env}" "${AGENT_DB_SIGNAL_PASSWORD:?missing in .env}"
DB="${ODOO_DB_NAME:-sentra}"

docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$DB" <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sentra_readonly') THEN
    CREATE ROLE sentra_readonly LOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sentra_signal') THEN
    CREATE ROLE sentra_signal LOGIN;
  END IF;
END
\$\$;
ALTER ROLE sentra_readonly WITH PASSWORD '${AGENT_DB_RO_PASSWORD}';
ALTER ROLE sentra_signal   WITH PASSWORD '${AGENT_DB_SIGNAL_PASSWORD}';
GRANT pg_monitor TO sentra_readonly;
ALTER ROLE sentra_readonly SET default_transaction_read_only = on;
ALTER ROLE sentra_readonly SET statement_timeout = '5s';
ALTER ROLE sentra_signal   SET statement_timeout = '5s';

-- Terminate one client backend of this database; refuses anything else.
CREATE OR REPLACE FUNCTION public.sentra_terminate_backend(target_pid integer)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS \$fn\$
DECLARE
  ok boolean;
BEGIN
  IF target_pid = pg_backend_pid() THEN
    RAISE EXCEPTION 'refusing to terminate own session';
  END IF;
  PERFORM 1 FROM pg_stat_activity
   WHERE pid = target_pid
     AND datname = current_database()
     AND backend_type = 'client backend'
     AND usename NOT IN ('sentra_readonly', 'sentra_signal', 'sentra_monitor');
  IF NOT FOUND THEN
    RAISE EXCEPTION 'pid % is not a terminable client backend of %', target_pid, current_database();
  END IF;
  SELECT pg_terminate_backend(target_pid) INTO ok;
  RETURN ok;
END
\$fn\$;

-- Make every Odoo worker drop its ORM/QWeb/routing caches on its next request.
CREATE OR REPLACE FUNCTION public.sentra_clear_odoo_cache()
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS \$fn\$
BEGIN
  PERFORM nextval('public.base_cache_signaling_default');
  PERFORM nextval('public.base_cache_signaling_assets');
  PERFORM nextval('public.base_cache_signaling_templates');
  PERFORM nextval('public.base_cache_signaling_routing');
  RETURN 4;
END
\$fn\$;

REVOKE ALL ON FUNCTION public.sentra_terminate_backend(integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.sentra_clear_odoo_cache() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.sentra_terminate_backend(integer) TO sentra_signal;
GRANT EXECUTE ON FUNCTION public.sentra_clear_odoo_cache() TO sentra_signal;
SQL
echo "agent DB roles ready in $DB"

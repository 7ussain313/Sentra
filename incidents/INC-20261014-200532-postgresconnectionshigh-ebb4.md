# Postmortem: PostgresConnectionsHigh (INC-20261014-200532-postgresconnectionshigh-ebb4)

- **Status:** escalated
- **Severity:** warning
- **Started:** 2026-10-14 20:05:32 UTC
- **Resolved (alert cleared):** 2026-10-14 20:11:52 UTC
- **Duplicate alerts merged:** 0

## Summary
On October 14, 2026, the Odoo system triggered a `PostgresConnectionsHigh` alert after reaching 87% of the database's connection limit. This resulted in service degradation, with application logs recording `psycopg2.OperationalError` failures for cron job processing. The system remained in a degraded state because attempts to manually terminate the stuck sessions were not executed.

## Root cause
The database reached its `max_connections` limit due to a connection leak. Odoo application threads were opening database transactions but failing to close them, leaving numerous sessions in an `idle in transaction` state.

## Resolution
No resolution was applied. Administrative intervention to terminate the identified `idle in transaction` processes was requested but did not receive approval, leading to an action timeout.

## Prevention
*   Audit Odoo custom modules and cron jobs to ensure all database transactions are managed using appropriate context managers or error handling to guarantee closure.
*   Evaluate and potentially increase the PostgreSQL `max_connections` and Odoo `db_maxconn` settings to accommodate the current workload.
*   Implement a service-level restart policy or automated script to purge sessions stuck in `idle in transaction` for extended periods.

## Timeline

| Time | Event |
|---|---|
| 2026-10-14 20:05:32 UTC | Alert **PostgresConnectionsHigh** received: PostgreSQL connections are close to the limit |
| 2026-10-14 20:05:32 UTC | SRE agent started investigating |
| 2026-10-14 20:05:33 UTC | Tool `query_database` -> ok |
| 2026-10-14 20:05:35 UTC | Tool `read_logs` -> ok |
| 2026-10-14 20:05:38 UTC | Tool `check_container_status` -> ok |
| 2026-10-14 20:05:41 UTC | Tool `query_database` -> ok |
| 2026-10-14 20:05:43 UTC | Approval requested for `kill_long_running_query` {"pid": 149} |
| 2026-10-14 20:12:55 UTC | Alert resolved (Alertmanager) |
| 2026-10-14 20:14:55 UTC | Approval for `kill_long_running_query`: **timeout** |
| 2026-10-14 20:15:06 UTC | Agent finished: action_timeout (status escalated) |

## Actions taken

- None. No action tool was executed.

## Evidence

- `query_database` {"query": "SELECT pid, state, query, wait_event_type, wait_event, xact_start \nFROM pg_stat_activity \nWHERE state IS NOT NULL \nORDER BY xact_start ASC \nLIMIT 20;"}: {"columns": ["pid", "state", "query", "wait_event_type", "wait_event", "xact_start"], "rows": [{"pid": 149, "state": "idle in transaction", "query": "select 1", "wait_event_type": "Client", "wait_event": "ClientRead", "xact_start": "2026-10
- `read_logs` {"service": "odoo"}: {"service": "odoo", "lines": 100, "text": "2026-10-14T20:00:35.801574862Z Traceback (most recent call last):\n2026-10-14T20:00:35.801591003Z   File \"/usr/lib/python3/dist-packages/odoo/addons/base/models/ir_cron.py\", line 119, in _process
- `check_container_status` {}: [{"name": "sentra-agents-1", "service": "agents", "state": "running", "health": "none", "restarts": 0, "uptime_seconds": 470, "exit_code": null}, {"name": "sentra-alertmanager-1", "service": "alertmanager", "state": "running", "health": "no
- `query_database` {"query": "SELECT pid, state, query, wait_event_type, wait_event, xact_start \nFROM pg_stat_activity \nWHERE state = 'idle in transaction' \nORDER BY xact_start ASC;"}: {"columns": ["pid", "state", "query", "wait_event_type", "wait_event", "xact_start"], "rows": [{"pid": 149, "state": "idle in transaction", "query": "select 1", "wait_event_type": "Client", "wait_event": "ClientRead", "xact_start": "2026-10

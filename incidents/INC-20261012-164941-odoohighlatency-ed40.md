# Postmortem: OdooHighLatency (INC-20261012-164941-odoohighlatency-ed40)

- **Status:** fixed
- **Severity:** warning
- **Started:** 2026-10-12 16:49:41 UTC
- **Resolved (alert cleared):** -
- **Duplicate alerts merged:** 0

## Summary
Scenario run.
## Root cause
See diagnosis.
## Resolution
See actions taken.
## Prevention
- Review alert thresholds and runbooks.

## Timeline

| Time | Event |
|---|---|
| 2026-10-12 16:49:41 UTC | Alert **OdooHighLatency** received: Odoo is slow or failing to serve pages |
| 2026-10-12 16:49:41 UTC | SRE agent started investigating |
| 2026-10-12 16:49:41 UTC | Tool `query_metrics` -> ok |
| 2026-10-12 16:49:41 UTC | Tool `query_database` -> ok |
| 2026-10-12 16:49:41 UTC | Tool `query_database` -> ok |
| 2026-10-12 16:49:41 UTC | Approval requested for `kill_long_running_query` {"pid": 671} |
| 2026-10-12 16:49:41 UTC | Approval for `kill_long_running_query`: **approved** by scenario-runner |
| 2026-10-12 16:49:41 UTC | Tool `kill_long_running_query` -> ok |
| 2026-10-12 16:50:01 UTC | Tool `query_metrics` -> ok |
| 2026-10-12 16:50:01 UTC | Agent finished: final (status fixed) |

## Actions taken

- `kill_long_running_query` {"pid": 671} -> ok (approval `7c21e3db157e`)

## Evidence

- `query_metrics` {"promql": "probe_duration_seconds{job=\"odoo-login\"}"}: {"resultType": "vector", "total_series": 1, "truncated": false, "series": [{"metric": {"__name__": "probe_duration_seconds", "instance": "http://odoo:8069/web/login", "job": "odoo-login"}, "value": "9.509047795"}]}
- `query_database` {"query": "select pid as blocked_pid, pg_blocking_pids(pid) as blockers, wait_event_type, extract(epoch from now() - query_start)::int as waiting_seconds from pg_stat_activity where cardinality(pg_blocking_pids(pid)) > 0 limit 10"}: {"columns": ["blocked_pid", "blockers", "wait_event_type", "waiting_seconds"], "rows": [{"blocked_pid": 34, "blockers": [671], "wait_event_type": "Lock", "waiting_seconds": 85}, {"blocked_pid": 701, "blockers": [671], "wait_event_type": "Lo
- `query_database` {"query": "select pid, application_name, state, extract(epoch from now() - xact_start)::int as xact_age_s from pg_stat_activity where pid = 671"}: {"columns": ["pid", "application_name", "state", "xact_age_s"], "rows": [{"pid": 671, "application_name": "nightly-report-job", "state": "idle in transaction", "xact_age_s": 100}], "truncated": false}
- `kill_long_running_query` {"pid": 671}: {"pid": 671, "success": true}
- `query_metrics` {"promql": "probe_success{job=\"odoo-login\"}"}: {"resultType": "vector", "total_series": 1, "truncated": false, "series": [{"metric": {"__name__": "probe_success", "instance": "http://odoo:8069/web/login", "job": "odoo-login"}, "value": "1"}]}

# Postmortem: PostgresConnectionsHigh (INC-20261012-164656-postgresconnectionshigh-3c7d)

- **Status:** fixed
- **Severity:** warning
- **Started:** 2026-10-12 16:46:56 UTC
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
| 2026-10-12 16:46:56 UTC | Alert **PostgresConnectionsHigh** received: PostgreSQL connections are close to the limit |
| 2026-10-12 16:46:56 UTC | SRE agent started investigating |
| 2026-10-12 16:46:56 UTC | Tool `query_metrics` -> ok |
| 2026-10-12 16:46:56 UTC | Tool `query_database` -> ok |
| 2026-10-12 16:46:56 UTC | Tool `query_database` -> ok |
| 2026-10-12 16:46:56 UTC | Approval requested for `kill_long_running_query` {"pid": 167} |
| 2026-10-12 16:46:56 UTC | Approval for `kill_long_running_query`: **approved** by scenario-runner |
| 2026-10-12 16:46:56 UTC | Tool `kill_long_running_query` -> ok |
| 2026-10-12 16:46:57 UTC | Approval requested for `kill_long_running_query` {"pid": 168} |
| 2026-10-12 16:46:57 UTC | Approval for `kill_long_running_query`: **approved** by scenario-runner |
| 2026-10-12 16:46:57 UTC | Tool `kill_long_running_query` -> ok |
| 2026-10-12 16:46:57 UTC | Approval requested for `kill_long_running_query` {"pid": 169} |
| 2026-10-12 16:46:57 UTC | Approval for `kill_long_running_query`: **approved** by scenario-runner |
| 2026-10-12 16:46:57 UTC | Tool `kill_long_running_query` -> ok |
| 2026-10-12 16:46:57 UTC | Approval requested for `kill_long_running_query` {"pid": 170} |
| 2026-10-12 16:46:57 UTC | Approval for `kill_long_running_query`: **approved** by scenario-runner |
| 2026-10-12 16:46:57 UTC | Tool `kill_long_running_query` -> ok |
| 2026-10-12 16:46:57 UTC | Approval requested for `kill_long_running_query` {"pid": 171} |
| 2026-10-12 16:46:57 UTC | Approval for `kill_long_running_query`: **approved** by scenario-runner |
| 2026-10-12 16:46:57 UTC | Tool `kill_long_running_query` -> ok |
| 2026-10-12 16:46:57 UTC | Approval requested for `kill_long_running_query` {"pid": 172} |
| 2026-10-12 16:46:57 UTC | Approval for `kill_long_running_query`: **approved** by scenario-runner |
| 2026-10-12 16:46:58 UTC | Tool `kill_long_running_query` -> ok |
| 2026-10-12 16:46:58 UTC | Approval requested for `kill_long_running_query` {"pid": 173} |
| 2026-10-12 16:46:58 UTC | Approval for `kill_long_running_query`: **approved** by scenario-runner |
| 2026-10-12 16:46:58 UTC | Tool `kill_long_running_query` -> ok |
| 2026-10-12 16:47:18 UTC | Tool `query_metrics` -> ok |
| 2026-10-12 16:47:18 UTC | Agent finished: final (status fixed) |

## Actions taken

- `kill_long_running_query` {"pid": 167} -> ok (approval `0fef865b0d80`)
- `kill_long_running_query` {"pid": 168} -> ok (approval `52d1853a0da6`)
- `kill_long_running_query` {"pid": 169} -> ok (approval `2bcc7d644a32`)
- `kill_long_running_query` {"pid": 170} -> ok (approval `e382b5dd6a0b`)
- `kill_long_running_query` {"pid": 171} -> ok (approval `19ec2f378ba8`)
- `kill_long_running_query` {"pid": 172} -> ok (approval `5d9859412422`)
- `kill_long_running_query` {"pid": 173} -> ok (approval `638ffd17d43d`)

## Evidence

- `query_metrics` {"promql": "sum(pg_stat_activity_count) / max(pg_settings_max_connections)"}: {"resultType": "vector", "total_series": 1, "truncated": false, "series": [{"metric": {}, "value": "0.86"}]}
- `query_database` {"query": "select application_name, state, count(*) as n, max(extract(epoch from now() - state_change))::int as idle_seconds from pg_stat_activity where backend_type = 'client backend' group by 1, 2 order by n desc limit 5"}: {"columns": ["application_name", "state", "n", "idle_seconds"], "rows": [{"application_name": "leaky-client", "state": "idle in transaction", "n": 83, "idle_seconds": 154}, {"application_name": "odoo-1", "state": "idle", "n": 1, "idle_secon
- `query_database` {"query": "select pid from pg_stat_activity where application_name = 'leaky-client' and state like 'idle in transaction%' order by state_change limit 7"}: {"columns": ["pid"], "rows": [{"pid": 167}, {"pid": 168}, {"pid": 169}, {"pid": 170}, {"pid": 171}, {"pid": 172}, {"pid": 173}], "truncated": false}
- `kill_long_running_query` {"pid": 167}: {"pid": 167, "success": true}
- `kill_long_running_query` {"pid": 168}: {"pid": 168, "success": true}
- `kill_long_running_query` {"pid": 169}: {"pid": 169, "success": true}
- `kill_long_running_query` {"pid": 170}: {"pid": 170, "success": true}
- `kill_long_running_query` {"pid": 171}: {"pid": 171, "success": true}
- `kill_long_running_query` {"pid": 172}: {"pid": 172, "success": true}
- `kill_long_running_query` {"pid": 173}: {"pid": 173, "success": true}
- `query_metrics` {"promql": "sum(pg_stat_activity_count) / max(pg_settings_max_connections)"}: {"resultType": "vector", "total_series": 1, "truncated": false, "series": [{"metric": {}, "value": "0.78"}]}

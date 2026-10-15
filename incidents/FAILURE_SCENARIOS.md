# Failure scenario results

Run: 2026-10-14 23:17. Agent model: **openai_compat:gemini-3.1-flash-lite**.

Failures are injected into the live stack. The alert chain (Prometheus -> Alertmanager -> agent webhook) and the tools are real. The reasoning step used the real model.

| Scenario | Alert | Alert fired | Agent got it | Agent action | Recovered | Result |
|---|---|---|---|---|---|---|
| Odoo container stopped | OdooDown | 89s | 89s | restart_service({"service": "odoo"}) | 106s | **PASS** |
| PostgreSQL container stopped | OdooDown | 83s | 90s | restart_service({"service": "db"}) | 107s | **PASS** |
| PostgreSQL connections nearly exhausted (leaked sessions) | PostgresConnectionsHigh | 138s | 150s | kill_long_running_query({"pid": 150}), kill_long_running_query({"pid": 151}), kill_long_running_query({"pid": 152}), kill_long_running_query({"pid": 153}), kill_long_running_query({"pid": 154}) | n/a | **FAIL** |
| Long-held lock blocks Odoo's queries | OdooHighLatency | 99s | 99s | kill_long_running_query({"pid": 1442}) | 126s | **PASS** |
| Python error in the custom module | OdooDown | 77s | 86s | none | 102s (manual) | **PASS** |

Times are seconds from the moment the failure was injected.

## Odoo container stopped

- Alert: `OdooDown`; fired after 89s, reached the agent after 89s.
- Incident: `INC-20261014-195940-odoodown-72b3` (postmortem `incidents/INC-20261014-195940-odoodown-72b3.md`), status **fixed**.
- Tools used: check_container_status:ok, read_logs:ok, read_logs:ok, restart_service:ok, check_container_status:ok.
- Recovery: 106s.

Diagnosis:

> ## Diagnosis
> The `odoo` container crashed due to an `OperationalError` (database connection failure) caused by a database shutdown, evidenced by the PostgreSQL logs receiving a "fast shutdown request" at `2026-10-14T19:54:03`. The Odoo container exited as a result.
> 
> ## Evidence
> - `check_container_status` showed `sentra-odoo-1` in `exited` state.
> - `odoo` logs showed repetitive `psycopg2.OperationalError: server closed the connection unexpectedly` followed by the service failing to connect to the database.
> - `db` logs confirmed that at `19:54:03` it received a "fast shutdown request", which shu

## PostgreSQL container stopped

- Alert: `OdooDown`; fired after 83s, reached the agent after 90s.
- Incident: `INC-20261014-200206-odoodown-900a` (postmortem `incidents/INC-20261014-200206-odoodown-900a.md`), status **fixed**.
- Tools used: check_container_status:ok, read_logs:ok, restart_service:ok, check_container_status:ok.
- Recovery: 107s.

Diagnosis:

> ## Diagnosis
> The database (`db`) container exited, causing the Odoo service to lose its database connection. The `db` logs indicate it received a "fast shutdown request" at 20:00:35, which caused it to stop. This was not a crash but an intentional shutdown.
> 
> ## Evidence
> *   `check_container_status` showed the `db` container in an `exited` state.
> *   `db` logs show `LOG: received fast shutdown request` at `2026-10-14 20:00:35 UTC`, which matches the alert time.
> 
> ## Proposed fix
> I have already triggered `restart_service(db)`. This is the standard procedure to recover from an unexpected database 

## PostgreSQL connections nearly exhausted (leaked sessions)

- Alert: `PostgresConnectionsHigh`; fired after 138s, reached the agent after 150s.
- Incident: `INC-20261014-200534-postgresconnectionshigh-225d` (postmortem `incidents/INC-20261014-200534-postgresconnectionshigh-225d.md`), status **escalated**.
- Tools used: check_container_status:ok, query_database:ok, read_logs:ok, query_database:ok, query_database:ok, query_database:rejected, query_database:ok, query_database:ok, kill_long_running_query:ok, query_database:ok, kill_long_running_query:ok, kill_long_running_query:ok, kill_long_running_query:ok, kill_long_running_query:ok.
- Recovery: Nones.

Diagnosis:

> ## Diagnosis
> PostgreSQL connections are saturated (92/100 active connections) due to a large number of "idle in transaction" sessions originating from the Odoo container. The database is functional, but the connection pool is nearly exhausted, which prevents new operations. Confidence: High.
> 
> ## Evidence
> *   **System State:** `pg_stat_activity` shows 92 current connections, 87-92% of the default `max_connections` (100).
> *   **Transaction Status:** A significant cluster of sessions are stuck in "idle in transaction" state, all executing a simple `select 1` query.
> *   **Odoo Behavior:** Odoo log

## Long-held lock blocks Odoo's queries

- Alert: `OdooHighLatency`; fired after 99s, reached the agent after 99s.
- Incident: `INC-20261014-201439-odoohighlatency-7e2f` (postmortem `incidents/INC-20261014-201439-odoohighlatency-7e2f.md`), status **fixed**.
- Tools used: check_container_status:ok, query_metrics:ok, read_logs:ok, query_database:ok, query_database:ok, query_database:ok, kill_long_running_query:ok, query_metrics:ok, query_database:ok.
- Recovery: 126s.

Diagnosis:

> ## Diagnosis
> Odoo was experiencing high latency (and consequently, failing login probes) due to a database lock contention. Specifically, a process (PID 1442) held an `AccessExclusiveLock` on the `res_users` table, which prevented other sessions from even reading from it, leading to a bottleneck. Confidence: High.
> 
> ## Evidence
> *   **Metrics:** `probe_duration_seconds` for `odoo-login` was ~9.5s.
> *   **Database:** `pg_stat_activity` showed multiple active queries waiting on `relation` locks for `res_users`.
> *   **Lock Analysis:** `pg_locks` confirmed that PID 1442 held an `AccessExclusiveLock` 

## Python error in the custom module

- Alert: `OdooDown`; fired after 77s, reached the agent after 86s.
- Incident: `INC-20261014-201704-odoodown-fca4` (postmortem `incidents/INC-20261014-201704-odoodown-fca4.md`), status **diagnosed**.
- Tools used: check_container_status:ok, read_logs:ok.
- Recovery: 102s via manual revert + restart (no safe automated fix).

Diagnosis:

> ## Diagnosis
> The `odoo` service is failing to start because of a `RuntimeError` in the custom `carwash` module (`/mnt/extra-addons/carwash/models/service.py`). This exception occurs during module loading, causing the Odoo registry to fail to initialize, which directly results in HTTP 500 errors for all requests, including the `/web/health` check. Confidence: High.
> 
> ## Evidence
> - Odoo logs show a `RuntimeError: scenario: simulated Python error in custom module` originating from `carwash/models/service.py`.
> - This error leads to `CRITICAL: Couldn't load module carwash` and `ERROR: Failed to load

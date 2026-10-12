# Failure scenario results

Run: 2026-10-12 19:53. Agent model: **scripted-adaptive (no API key)**.

Failures are injected into the live stack. The alert chain (Prometheus -> Alertmanager -> agent webhook) and the tools are real. The reasoning step used a scripted adaptive stand-in because no `ANTHROPIC_API_KEY` was configured: it reads the real tool output to choose its next call, so it validates that the evidence is available and the actions work, **not** the quality of a real model's diagnosis. Re-run with a key to evaluate the model.

| Scenario | Alert | Alert fired | Agent got it | Agent action | Recovered | Result |
|---|---|---|---|---|---|---|
| Odoo container stopped | OdooDown | 84s | 84s | restart_service({"service": "odoo"}) | 111s | **PASS** |
| PostgreSQL container stopped | OdooDown | 89s | 95s | restart_service({"service": "db"}) | 126s | **PASS** |
| PostgreSQL connections nearly exhausted (leaked sessions) | PostgresConnectionsHigh | 148s | 157s | kill_long_running_query({"pid": 167}), kill_long_running_query({"pid": 168}), kill_long_running_query({"pid": 169}), kill_long_running_query({"pid": 170}), kill_long_running_query({"pid": 171}), kill_long_running_query({"pid": 172}), kill_long_running_query({"pid": 173}) | 182s | **PASS** |
| Long-held lock blocks Odoo's queries | OdooHighLatency | 93s | 100s | kill_long_running_query({"pid": 671}) | 121s | **PASS** |
| Python error in the custom module | OdooDown | 74s | 86s | none | 92s (manual) | **PASS** |

Times are seconds from the moment the failure was injected.

## Odoo container stopped

- Alert: `OdooDown`; fired after 84s, reached the agent after 84s.
- Incident: `INC-20261012-164035-odoodown-bc60` (postmortem `incidents/INC-20261012-164035-odoodown-bc60.md`), status **fixed**.
- Tools used: check_container_status:ok, read_logs:ok, query_metrics:ok, restart_service:ok, check_container_status:ok.
- Recovery: 111s.

Diagnosis:

> ## Diagnosis
> The odoo container was not running (state exited, exit 0). High confidence.
> ## Evidence
> - container status
> - probe_success = 0
> ## Proposed fix
> restart_service(odoo)
> ## Result
> Odoo is now running.

## PostgreSQL container stopped

- Alert: `OdooDown`; fired after 89s, reached the agent after 95s.
- Incident: `INC-20261012-164312-odoodown-c13f` (postmortem `incidents/INC-20261012-164312-odoodown-c13f.md`), status **fixed**.
- Tools used: check_container_status:ok, read_logs:ok, restart_service:ok, check_container_status:ok, query_metrics:ok.
- Recovery: 126s.

Diagnosis:

> ## Diagnosis
> PostgreSQL container was not running (state exited). Odoo failed as a consequence. High confidence.
> ## Proposed fix
> restart_service(db)
> ## Result
> db is now running.

## PostgreSQL connections nearly exhausted (leaked sessions)

- Alert: `PostgresConnectionsHigh`; fired after 148s, reached the agent after 157s.
- Incident: `INC-20261012-164656-postgresconnectionshigh-3c7d` (postmortem `incidents/INC-20261012-164656-postgresconnectionshigh-3c7d.md`), status **fixed**.
- Tools used: query_metrics:ok, query_database:ok, query_database:ok, kill_long_running_query:ok, kill_long_running_query:ok, kill_long_running_query:ok, kill_long_running_query:ok, kill_long_running_query:ok, kill_long_running_query:ok, kill_long_running_query:ok, query_metrics:ok.
- Recovery: 182s.

Diagnosis:

> ## Diagnosis
> Client 'leaky-client' holds 83 idle-in-transaction connections and exhausts the pool. High confidence.
> ## Proposed fix
> Terminated 7 of its sessions; the owner of that client must fix the leak.
> ## Result
> Usage dropped below the alert threshold.

## Long-held lock blocks Odoo's queries

- Alert: `OdooHighLatency`; fired after 93s, reached the agent after 100s.
- Incident: `INC-20261012-164941-odoohighlatency-ed40` (postmortem `incidents/INC-20261012-164941-odoohighlatency-ed40.md`), status **fixed**.
- Tools used: query_metrics:ok, query_database:ok, query_database:ok, kill_long_running_query:ok, query_metrics:ok.
- Recovery: 121s.

Diagnosis:

> ## Diagnosis
> A long-held lock by 'nightly-report-job' (pid 671) blocked Odoo's queries. High confidence.
> ## Proposed fix
> Terminate the blocking session.
> ## Result
> Login page responds again.

## Python error in the custom module

- Alert: `OdooDown`; fired after 74s, reached the agent after 86s.
- Incident: `INC-20261012-165212-odoodown-0c00` (postmortem `incidents/INC-20261012-165212-odoodown-0c00.md`), status **diagnosed**.
- Tools used: check_container_status:ok, read_logs:ok.
- Recovery: 92s via manual revert + restart (no safe automated fix).

Diagnosis:

> ## Diagnosis
> Odoo is running but fails to load the registry because of a Python error in a custom module: `RuntimeError: scenario: simulated Python error in custom module`. High confidence (traceback in logs).
> ## Evidence
> - odoo container state: running
> - Traceback in Odoo logs
> ## Proposed fix
> none: escalate. A restart cannot fix a code error; a developer must fix or revert the module change.

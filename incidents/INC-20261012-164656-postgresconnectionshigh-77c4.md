# Postmortem: PostgresConnectionsHigh (INC-20261012-164656-postgresconnectionshigh-77c4)

- **Status:** agent_unavailable
- **Severity:** warning
- **Started:** 2026-10-12 16:46:56 UTC
- **Resolved (alert cleared):** 2026-10-12 16:47:07 UTC
- **Duplicate alerts merged:** 0

## Summary
Alert PostgresConnectionsHigh fired and the SRE agent investigated (final status: agent_unavailable).

## Root cause
Agent unavailable: ANTHROPIC_API_KEY is not configured. Raw alert: 86% of max_connections is in use.

## Resolution
No automated fix was applied. A human should review the diagnosis above.

## Prevention
Not generated automatically (the language model was unavailable); review the timeline.


## Timeline

| Time | Event |
|---|---|
| 2026-10-12 16:46:56 UTC | Alert **PostgresConnectionsHigh** received: PostgreSQL connections are close to the limit |
| 2026-10-12 16:46:56 UTC | LLM unavailable: ANTHROPIC_API_KEY is not configured |
| 2026-10-12 16:46:56 UTC | Agent finished: llm_unavailable (status agent_unavailable) |
| 2026-10-12 16:47:55 UTC | Alert resolved (Alertmanager) |

## Actions taken

- None. No action tool was executed.

## Evidence

- No tool evidence was collected.

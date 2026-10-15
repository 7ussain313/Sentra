# Demo walkthrough (about 3 minutes)

Run this live to see Sentra work end to end. It is written as a script, so it also works as a screen
recording if you ever want one.

## Before recording

- [ ] `docker compose up -d`; `http://localhost:8000/health` returns ok.
- [ ] LLM key is set in `.env` and a test question works in **Ask**.
- [ ] Log in once to Odoo (`manager`), Grafana and the Sentra UI so browser auth prompts do not appear.
- [ ] Open four tabs in this order: Odoo Car Wash, Grafana "Sentra - Odoo Health", Sentra UI
      (Incidents), a terminal.
- [ ] The free Gemini tier has daily request limits: run one practice take, then record soon after.

## Script

| Time | Screen | Say / do |
|------|--------|----------|
| 0:00 | Odoo, **Car Wash > Bookings** | "Sentra is an AI SRE for Odoo. This is a car wash ERP: bookings, vehicles, services." Open one booking and show the state buttons. |
| 0:25 | Grafana, *Odoo Health* | "Prometheus watches it. Everything is green: Odoo up, response time about 40 ms, no alerts." |
| 0:40 | Terminal | Run `docker compose stop odoo`. "I'm breaking Odoo on purpose." |
| 0:50 | Grafana | Show Odoo status turning DOWN. "Alertmanager fires `OdooDown` and posts it to the agent service." |
| 1:20 | Sentra UI, **Incidents** | A new incident appears. Open it. "The agent checked container status and logs, and found Odoo had exited." Scroll through the steps and the diagnosis. |
| 1:50 | Incident detail | "It proposes `restart_service(odoo)`. It cannot run this itself." Click **Approve**. |
| 2:05 | Incident detail | Show the action running and the verification step; Odoo status goes back to UP. "Then it verifies and writes a postmortem." Open the postmortem. |
| 2:30 | Sentra UI, **Ask** | Click "Which service is most popular this month?". "A second, read-only agent answers business questions from live Odoo data." Show the answer and the queries used. |
| 2:50 | Sentra UI, **Audit** | "Every tool call and approval is in the audit log." Done. |

## Talking points if you have time

- Human approval is mandatory and single use; the agent never gets a shell.
- The database role the agent uses cannot read business tables, and Odoo itself rejects writes from
  the agent's API user.
- Honest limitation: a very large connection leak needs one approval per session (see README).


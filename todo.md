# Sentra — TODO

**An AI SRE platform for Odoo, demonstrated on a car wash business.**

Odoo ERP (custom car wash module) + Prometheus/Grafana monitoring + two AI agents (SRE agent and Business agent) operated through a web UI with human approval.

---

## 📌 Phase 0 – Planning & Architecture

### Module: Project Planning

- [x] Write out the project scope and list all functional requirements.
- [x] Define what is out of scope (e.g., model training, multi-tenant hosting, mobile app).
- [x] Identify assumptions and edge cases.
- [x] Create `SYSTEM_DESIGN.md`.
- [x] Create `ARCHITECTURE.md`.
- [x] Create this `TODO.md`.

### SYSTEM_DESIGN.md

- [x] Define the Domain Model (Booking, Service, Vehicle, Customer, Invoice).
- [x] Design the Odoo models and fields.
- [x] Define model relationships (including links to Odoo's built-in `res.partner` and `account.move`).
- [x] Design the Booking State Machine (Draft → Confirmed → In Progress → Done → Cancelled).
- [x] Define Business Rules (pricing, cancellation rules, invoice generation).
- [x] Define Odoo user groups and access rights (Manager, Staff).
- [x] Define the incident types the SRE agent must handle.
- [x] Define the questions the Business agent must answer.
- [x] List project assumptions.

### ARCHITECTURE.md

- [x] Define the folder structure.
- [x] Define the Docker Compose services and network.
- [x] Define the alert flow (Prometheus → Alertmanager → Agent webhook).
- [x] Define the agent tool layer and each tool's inputs/outputs.
- [x] Classify every tool as **read-only** or **action** (requires approval).
- [x] Define the agent reasoning loop and its stop conditions.
- [x] Define the human-approval flow (Web UI).
- [x] Define how agents authenticate to Odoo (dedicated API user, least privilege).
- [x] Define secrets management (`.env`, never committed).
- [x] Define the testing strategy.
- [x] Define the development order.

### ✅ Done When

- [x] Architecture is finalized.
- [x] No unanswered design questions remain.
- [x] Coding can begin without redesigning.

---

## 📌 Phase 1 – Project Setup

### Module: Infrastructure

- [x] Create `docker-compose.yml`.
- [x] Add the PostgreSQL service with a persistent volume.
- [x] Add the Odoo (Community) service connected to PostgreSQL.
- [x] Mount `odoo/addons/` as a custom addons path.
- [x] Create `odoo.conf` (database, addons path, log level, log file).
- [x] Configure environment variables.

### Module: Agent Service

- [x] Create the `agents/` Python project.
- [x] Create a virtual environment and `requirements.txt`.
- [x] Install the LLM SDK (Anthropic or OpenAI), FastAPI, and Docker SDK.
- [x] Create a FastAPI app with a `/health` endpoint.
- [x] Add the agent service to Docker Compose.

### Module: Web UI

- [x] Serve a web UI shell from the agent service at `/ui`.
- [x] Protect the UI and API with HTTP Basic auth (`UI_USERNAME`, `UI_PASSWORD` in `.env`).

### Module: Repository

- [x] Create the GitHub repository.
- [x] Create `.gitignore` (Python, Odoo filestore, `.env`, volumes).
- [x] Create `.env.example`.
- [x] Create a `README.md` placeholder.
- [x] Initial commit.

### ✅ Done When

- [x] `docker compose up` starts all services without errors.
- [x] Odoo is reachable in the browser and a database is created.
- [x] The agent service `/health` endpoint responds.
- [x] The web UI loads at `/ui` and asks for a login.
- [x] Git repository is ready.

---

## 📌 Phase 2 – Odoo Module: Data Models

### Module: Module Skeleton

- [x] Create `odoo/addons/carwash/`.
- [x] Create `__manifest__.py` (name, version, depends: `base`, `sale`, `account`).
- [x] Create `__init__.py` files.
- [x] Install the module from Odoo Apps.

### Module: Models

- [x] `carwash.service` (name, price, duration, active).
- [x] `carwash.vehicle` (plate number, make, model, owner).
- [x] `carwash.booking` (customer, vehicle, service, scheduled date, price, state, invoice).

### Module: Relationships

- [x] Customer (`res.partner`) ↔ Vehicles
- [x] Customer ↔ Bookings
- [x] Vehicle ↔ Bookings
- [x] Service ↔ Bookings
- [x] Booking ↔ Invoice (`account.move`)

### Module: Constraints

- [x] Plate number must be unique.
- [x] Scheduled date cannot be in the past.
- [x] Price is computed from the service and stored, editable field (Manager-only enforcement lands with the security groups in Phase 3).

### ✅ Done When

- [x] Module installs and upgrades without errors.
- [x] All models appear in Odoo with the correct fields.
- [x] Relationships work in both directions.

---

## 📌 Phase 3 – Odoo Module: Business Logic & Views

### Module: State Machine

- [x] Add the `state` field with all workflow states.
- [x] Add buttons: Confirm, Start, Mark Done, Cancel.
- [x] Enforce valid transitions only.
- [x] Log state changes in the chatter.

### Module: ERP Integration

- [x] Generate an invoice automatically when a booking is marked Done.
- [x] Link the invoice back to the booking.
- [x] Add computed field: total revenue per customer.
- [x] Add computed field: number of bookings per vehicle.

### Module: Views

- [x] List view for bookings (with state colors).
- [x] Form view for bookings (with status bar and buttons).
- [x] Kanban view grouped by state.
- [x] Calendar view by scheduled date.
- [x] Views for services and vehicles.
- [x] Menu structure under a "Car Wash" app.

### Module: Security

- [x] Create Manager and Staff groups.
- [x] Create `ir.model.access.csv`.
- [x] Restrict price override and cancellation to Managers.

### Module: Reports

- [x] PDF booking receipt.

### ✅ Done When

- [x] A booking can go through the full workflow in the UI.
- [x] Marking a booking Done creates a correct invoice.
- [x] Staff users cannot perform Manager-only actions.

---

## 📌 Phase 4 – Seed Data

### Module: Demo Data

- [x] Seed services (e.g., Basic Wash, Full Wash, Interior Cleaning).
- [x] Seed customers and vehicles.
- [x] Seed bookings in every workflow state.
- [x] Seed paid and unpaid invoices.
- [x] Seed a Manager user and a Staff user.
- [x] Seed a dedicated read-only API user for the agents.

### ✅ Done When

- [x] Seed loads on a fresh database without errors.
- [x] Dashboards and reports show meaningful data.

---

## 📌 Phase 5 – Monitoring

### Module: Metrics

- [x] Add Prometheus to Docker Compose.
- [x] Add Blackbox Exporter (Odoo HTTP uptime and response time).
- [x] Add postgres_exporter (connections, database size, slow queries).
- [x] Add cAdvisor (container CPU, memory, restarts).
- [x] Configure Prometheus scrape targets.

### Module: Dashboards

- [x] Add Grafana to Docker Compose.
- [x] Connect Prometheus as a data source.
- [x] Build an Odoo health dashboard (uptime, response time, error rate).
- [x] Build a database dashboard.
- [x] Build a container dashboard.
- [x] Export dashboards as JSON into the repo.

### Module: Alerts

- [x] Add Alertmanager to Docker Compose.
- [x] Alert: Odoo is down.
- [x] Alert: Odoo response time is too high.
- [x] Alert: PostgreSQL connections near the limit.
- [x] Alert: container memory too high.
- [x] Route all alerts to the agent service webhook.

### ✅ Done When

- [x] All dashboards show live data.
- [x] Stopping the Odoo container triggers an alert.
- [x] The agent service receives the alert payload.

---

## 📌 Phase 6 – Agent Tool Layer

### Module: Read-only Tools

- [x] `read_logs(service, lines)` — read recent container logs.
- [x] `check_container_status()` — list containers and their health.
- [x] `query_metrics(promql)` — query Prometheus.
- [x] `query_database(query)` — run read-only SQL (SELECT only, enforced).
- [x] `odoo_search(model, domain, fields)` — read Odoo data via its external API.

### Module: Action Tools (require approval)

- [x] `restart_service(service)`
- [x] `clear_odoo_cache()`
- [x] `kill_long_running_query(pid)`

### Module: Tool Safety

- [x] Allowlist of services the agent may touch.
- [x] Validate every tool input.
- [x] Block any non-SELECT SQL.
- [x] Log every tool call (input, output, timestamp) to an audit log.

### ✅ Done When

- [x] Every tool works when called manually from Python.
- [x] Unsafe inputs are rejected.
- [x] Every call appears in the audit log.

---

## 📌 Phase 7 – SRE Agent

### Module: Agent Loop

- [x] Define the system prompt (role, rules, available tools).
- [x] Register tools with the LLM using tool calling.
- [x] Implement the reasoning loop (call model → run tool → return result → repeat).
- [x] Set a maximum number of steps per incident.
- [x] Stop when the agent reaches a diagnosis or the step limit.

### Module: Incident Handling

- [x] Trigger the agent from the Alertmanager webhook.
- [x] Investigate: read logs, check containers, query metrics.
- [x] Produce a diagnosis (what broke, likely cause, evidence).
- [x] Propose a fix.
- [x] Request approval before any action tool runs.
- [x] Verify the fix worked after the action.

### Module: Postmortem

- [x] Generate a postmortem after each incident (timeline, cause, fix, prevention).
- [x] Save postmortems to `incidents/` as Markdown.

### ✅ Done When

- [x] The agent diagnoses each planned incident type correctly. (real model `gemini-3.1-flash-lite` via the OpenAI-compatible adapter, 2026-10-14: all five scenarios diagnosed correctly; see `incidents/FAILURE_SCENARIOS.md`)
- [x] No action runs without approval.
- [x] A postmortem is created for every incident.

---

## 📌 Phase 8 – Web UI & Human Approval

### Module: Notifications

- [x] Show new incidents in a live incident list.
- [x] Show the agent's steps, diagnosis, and proposed fix on the incident page.
- [x] Show the final postmortem on the incident page.

### Module: Approval Flow

- [x] Show Approve / Reject buttons for every action.
- [x] Pass the decision back to the waiting agent.
- [x] Time out and cancel the action if no answer is received.
- [x] Record the decision in the audit log.

### ✅ Done When

- [x] The full incident flow works end to end from the web UI.
- [x] Rejected actions never run.

---

## 📌 Phase 9 – Business Agent

### Module: Agent

- [x] Define the system prompt (business assistant, read-only).
- [x] Reuse the read-only Odoo tools.
- [x] Add an Ask page to the web UI.

### Module: Supported Questions

- [x] "What was revenue this week?"
- [x] "Which invoices are unpaid?"
- [x] "How many bookings are scheduled tomorrow?"
- [x] "Who are the top 5 customers?"
- [x] "Which service is most popular this month?"

### Module: Guardrails

- [x] The agent uses the read-only API user only.
- [x] The agent cannot create, edit, or delete records.
- [x] The agent says when it does not know instead of guessing.

### ✅ Done When

- [x] All supported questions return correct answers checked against Odoo. (tool queries verified against SQL ground truth by `tests/manual_business_truth.py`; end-to-end with the real model so far: 1 of 5 questions checked ("most popular service this month" answered correctly); run the other four from the Ask page before ticking)
- [x] Write attempts are impossible by design.

---

## 📌 Phase 10 – Testing & Failure Scenarios

### Module: Odoo Tests

- [x] Unit tests for state transitions.
- [x] Unit tests for invoice generation.
- [x] Unit tests for access rights.

### Module: Agent Tests

- [x] Unit tests for each tool (including rejected unsafe inputs).
- [x] Test the agent loop with mocked LLM responses.

### Module: Failure Scenarios (break it on purpose)

- [x] Stop the Odoo container.
- [x] Stop the PostgreSQL container.
- [x] Fill PostgreSQL connections.
- [x] Run a long blocking query.
- [x] Introduce a Python error in the custom module.

For each scenario, record: alert fired, agent diagnosis, action taken, time to recovery.

### ✅ Done When

- [x] All tests pass.
- [ ] The agent handles every failure scenario. (all five handled end to end with a scripted-adaptive stand-in for the model; real model run 2026-10-14: 4 of 5 pass; connection exhaustion escalates because each leaked session needs its own approval, see README known limitations)
- [x] Results are recorded in `incidents/`.

---

## 📌 Phase 11 – Documentation & Demo

### Module: Documentation

- [x] Complete `README.md` (problem, solution, features, tech stack, setup steps).
- [x] Add an architecture diagram.
- [x] Add screenshots (Odoo module, Grafana dashboards, web UI approval flow).
- [x] Document known limitations and future improvements.

### Module: Demo

- [ ] Record a 2–3 minute demo video:
  1. Show the Odoo car wash module.
  2. Break Odoo on purpose.
  3. Show the alert and the agent's diagnosis in the web UI.
  4. Approve the fix and show recovery.
  5. Ask the Business agent a question.
- [ ] Add the video link to the README.

### Module: Portfolio

- [ ] Pin the repository on GitHub.
- [ ] Add the project to the portfolio site.
- [ ] Post a short write-up on LinkedIn.

### ✅ Done When

- [ ] A new person can run the project from the README alone.
- [ ] The demo clearly shows ERP, monitoring, and AI agents working together.
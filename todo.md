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

- [ ] Create the GitHub repository.
- [x] Create `.gitignore` (Python, Odoo filestore, `.env`, volumes).
- [x] Create `.env.example`.
- [x] Create a `README.md` placeholder.
- [x] Initial commit.

### ✅ Done When

- [ ] `docker compose up` starts all services without errors.
- [ ] Odoo is reachable in the browser and a database is created.
- [ ] The agent service `/health` endpoint responds.
- [ ] The web UI loads at `/ui` and asks for a login.
- [x] Git repository is ready.

---

## 📌 Phase 2 – Odoo Module: Data Models

### Module: Module Skeleton

- [ ] Create `odoo/addons/carwash/`.
- [ ] Create `__manifest__.py` (name, version, depends: `base`, `sale`, `account`).
- [ ] Create `__init__.py` files.
- [ ] Install the module from Odoo Apps.

### Module: Models

- [ ] `carwash.service` (name, price, duration, active).
- [ ] `carwash.vehicle` (plate number, make, model, owner).
- [ ] `carwash.booking` (customer, vehicle, service, scheduled date, price, state, invoice).

### Module: Relationships

- [ ] Customer (`res.partner`) ↔ Vehicles
- [ ] Customer ↔ Bookings
- [ ] Vehicle ↔ Bookings
- [ ] Service ↔ Bookings
- [ ] Booking ↔ Invoice (`account.move`)

### Module: Constraints

- [ ] Plate number must be unique.
- [ ] Scheduled date cannot be in the past.
- [ ] Price is computed from the service but can be overridden by a Manager.

### ✅ Done When

- [ ] Module installs and upgrades without errors.
- [ ] All models appear in Odoo with the correct fields.
- [ ] Relationships work in both directions.

---

## 📌 Phase 3 – Odoo Module: Business Logic & Views

### Module: State Machine

- [ ] Add the `state` field with all workflow states.
- [ ] Add buttons: Confirm, Start, Mark Done, Cancel.
- [ ] Enforce valid transitions only.
- [ ] Log state changes in the chatter.

### Module: ERP Integration

- [ ] Generate an invoice automatically when a booking is marked Done.
- [ ] Link the invoice back to the booking.
- [ ] Add computed field: total revenue per customer.
- [ ] Add computed field: number of bookings per vehicle.

### Module: Views

- [ ] List view for bookings (with state colors).
- [ ] Form view for bookings (with status bar and buttons).
- [ ] Kanban view grouped by state.
- [ ] Calendar view by scheduled date.
- [ ] Views for services and vehicles.
- [ ] Menu structure under a "Car Wash" app.

### Module: Security

- [ ] Create Manager and Staff groups.
- [ ] Create `ir.model.access.csv`.
- [ ] Restrict price override and cancellation to Managers.

### Module: Reports

- [ ] PDF booking receipt.

### ✅ Done When

- [ ] A booking can go through the full workflow in the UI.
- [ ] Marking a booking Done creates a correct invoice.
- [ ] Staff users cannot perform Manager-only actions.

---

## 📌 Phase 4 – Seed Data

### Module: Demo Data

- [ ] Seed services (e.g., Basic Wash, Full Wash, Interior Cleaning).
- [ ] Seed customers and vehicles.
- [ ] Seed bookings in every workflow state.
- [ ] Seed paid and unpaid invoices.
- [ ] Seed a Manager user and a Staff user.
- [ ] Seed a dedicated read-only API user for the agents.

### ✅ Done When

- [ ] Seed loads on a fresh database without errors.
- [ ] Dashboards and reports show meaningful data.

---

## 📌 Phase 5 – Monitoring

### Module: Metrics

- [ ] Add Prometheus to Docker Compose.
- [ ] Add Blackbox Exporter (Odoo HTTP uptime and response time).
- [ ] Add postgres_exporter (connections, database size, slow queries).
- [ ] Add cAdvisor (container CPU, memory, restarts).
- [ ] Configure Prometheus scrape targets.

### Module: Dashboards

- [ ] Add Grafana to Docker Compose.
- [ ] Connect Prometheus as a data source.
- [ ] Build an Odoo health dashboard (uptime, response time, error rate).
- [ ] Build a database dashboard.
- [ ] Build a container dashboard.
- [ ] Export dashboards as JSON into the repo.

### Module: Alerts

- [ ] Add Alertmanager to Docker Compose.
- [ ] Alert: Odoo is down.
- [ ] Alert: Odoo response time is too high.
- [ ] Alert: PostgreSQL connections near the limit.
- [ ] Alert: container memory too high.
- [ ] Route all alerts to the agent service webhook.

### ✅ Done When

- [ ] All dashboards show live data.
- [ ] Stopping the Odoo container triggers an alert.
- [ ] The agent service receives the alert payload.

---

## 📌 Phase 6 – Agent Tool Layer

### Module: Read-only Tools

- [ ] `read_logs(service, lines)` — read recent container logs.
- [ ] `check_container_status()` — list containers and their health.
- [ ] `query_metrics(promql)` — query Prometheus.
- [ ] `query_database(query)` — run read-only SQL (SELECT only, enforced).
- [ ] `odoo_search(model, domain, fields)` — read Odoo data via its external API.

### Module: Action Tools (require approval)

- [ ] `restart_service(service)`
- [ ] `clear_odoo_cache()`
- [ ] `kill_long_running_query(pid)`

### Module: Tool Safety

- [ ] Allowlist of services the agent may touch.
- [ ] Validate every tool input.
- [ ] Block any non-SELECT SQL.
- [ ] Log every tool call (input, output, timestamp) to an audit log.

### ✅ Done When

- [ ] Every tool works when called manually from Python.
- [ ] Unsafe inputs are rejected.
- [ ] Every call appears in the audit log.

---

## 📌 Phase 7 – SRE Agent

### Module: Agent Loop

- [ ] Define the system prompt (role, rules, available tools).
- [ ] Register tools with the LLM using tool calling.
- [ ] Implement the reasoning loop (call model → run tool → return result → repeat).
- [ ] Set a maximum number of steps per incident.
- [ ] Stop when the agent reaches a diagnosis or the step limit.

### Module: Incident Handling

- [ ] Trigger the agent from the Alertmanager webhook.
- [ ] Investigate: read logs, check containers, query metrics.
- [ ] Produce a diagnosis (what broke, likely cause, evidence).
- [ ] Propose a fix.
- [ ] Request approval before any action tool runs.
- [ ] Verify the fix worked after the action.

### Module: Postmortem

- [ ] Generate a postmortem after each incident (timeline, cause, fix, prevention).
- [ ] Save postmortems to `incidents/` as Markdown.

### ✅ Done When

- [ ] The agent diagnoses each planned incident type correctly.
- [ ] No action runs without approval.
- [ ] A postmortem is created for every incident.

---

## 📌 Phase 8 – Web UI & Human Approval

### Module: Notifications

- [ ] Show new incidents in a live incident list.
- [ ] Show the agent's steps, diagnosis, and proposed fix on the incident page.
- [ ] Show the final postmortem on the incident page.

### Module: Approval Flow

- [ ] Show Approve / Reject buttons for every action.
- [ ] Pass the decision back to the waiting agent.
- [ ] Time out and cancel the action if no answer is received.
- [ ] Record the decision in the audit log.

### ✅ Done When

- [ ] The full incident flow works end to end from the web UI.
- [ ] Rejected actions never run.

---

## 📌 Phase 9 – Business Agent

### Module: Agent

- [ ] Define the system prompt (business assistant, read-only).
- [ ] Reuse the read-only Odoo tools.
- [ ] Add an Ask page to the web UI.

### Module: Supported Questions

- [ ] "What was revenue this week?"
- [ ] "Which invoices are unpaid?"
- [ ] "How many bookings are scheduled tomorrow?"
- [ ] "Who are the top 5 customers?"
- [ ] "Which service is most popular this month?"

### Module: Guardrails

- [ ] The agent uses the read-only API user only.
- [ ] The agent cannot create, edit, or delete records.
- [ ] The agent says when it does not know instead of guessing.

### ✅ Done When

- [ ] All supported questions return correct answers checked against Odoo.
- [ ] Write attempts are impossible by design.

---

## 📌 Phase 10 – Testing & Failure Scenarios

### Module: Odoo Tests

- [ ] Unit tests for state transitions.
- [ ] Unit tests for invoice generation.
- [ ] Unit tests for access rights.

### Module: Agent Tests

- [ ] Unit tests for each tool (including rejected unsafe inputs).
- [ ] Test the agent loop with mocked LLM responses.

### Module: Failure Scenarios (break it on purpose)

- [ ] Stop the Odoo container.
- [ ] Stop the PostgreSQL container.
- [ ] Fill PostgreSQL connections.
- [ ] Run a long blocking query.
- [ ] Introduce a Python error in the custom module.

For each scenario, record: alert fired, agent diagnosis, action taken, time to recovery.

### ✅ Done When

- [ ] All tests pass.
- [ ] The agent handles every failure scenario.
- [ ] Results are recorded in `incidents/`.

---

## 📌 Phase 11 – Documentation & Demo

### Module: Documentation

- [ ] Complete `README.md` (problem, solution, features, tech stack, setup steps).
- [ ] Add an architecture diagram.
- [ ] Add screenshots (Odoo module, Grafana dashboards, web UI approval flow).
- [ ] Document known limitations and future improvements.

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
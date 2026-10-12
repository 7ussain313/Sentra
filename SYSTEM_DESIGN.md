# Sentra — System Design

An AI SRE platform for Odoo, demonstrated on a car wash business.

---

## 1. Scope

### 1.1 Problem
Small businesses running Odoo have no on-call engineer. When Odoo or its database breaks, nobody notices until customers complain. Sentra watches the stack, diagnoses incidents with an AI agent, and asks a human to approve any fix in a web UI. A second agent answers business questions from Odoo data.

### 1.2 Functional requirements

| ID | Requirement |
|----|-------------|
| F1 | Odoo module `carwash` manages services, vehicles, customers, and bookings. |
| F2 | Bookings follow a state machine and generate an invoice when done. |
| F3 | Prometheus + Grafana monitor Odoo uptime/latency, PostgreSQL, and containers. |
| F4 | Alertmanager sends alerts to the SRE agent via webhook. |
| F5 | The SRE agent investigates with read-only tools and produces a diagnosis. |
| F6 | The SRE agent proposes a fix; action tools run only after human approval in the web UI. |
| F7 | The SRE agent writes a Markdown postmortem for every incident. |
| F8 | The Business agent answers read-only questions about revenue, invoices, bookings, customers, and services via the web UI's Ask page. |
| F9 | Every tool call and approval decision is written to an audit log. |

### 1.3 Out of scope
* Model training or fine-tuning.
* Multi-tenant hosting.
* Mobile app or customer-facing web portal.
* Kubernetes or cloud deployment (Docker Compose on one host only).
* Payments, POS hardware, inventory, HR, or payroll.
* Autonomous actions without approval.
* Agents writing to Odoo business data.

### 1.4 Assumptions
* Single host running Docker Compose; the agent has access to the Docker socket.
* One operator (the owner) with one browser login (HTTP Basic auth).
* Odoo 17 Community, PostgreSQL 15.
* One company, one currency, one branch.
* LLM access via the Anthropic API (key in `.env`).
* Incident volume is low; incidents are handled one at a time.

### 1.5 Edge cases
* Alert storm: duplicate alerts for the same incident are deduplicated by alert name + 10-minute window.
* Odoo down means the Business agent cannot answer; it says so rather than guessing.
* Approval never arrives: the action times out after 10 minutes and is cancelled.
* LLM API unavailable: show the raw alert in the web UI with "agent unavailable".
* Agent hits the step limit without a diagnosis: report evidence gathered so far and escalate to the human.
* Agent proposes an action on a service outside the allowlist: rejected before it reaches the human.
* Unauthenticated web UI request: rejected with 401 and logged.
* Booking scheduled in the past, duplicate plate number, or invoice creation failure: rejected with a clear error; the booking stays in its current state.

---

## 2. Domain Model

```
res.partner (Customer) 1 ──< carwash.vehicle
res.partner            1 ──< carwash.booking
carwash.vehicle        1 ──< carwash.booking
carwash.service        1 ──< carwash.booking
carwash.booking        1 ── 0..1 account.move (Invoice)
```

### 2.1 Models and fields

**`carwash.service`**
| Field | Type | Notes |
|-------|------|-------|
| name | Char | required |
| price | Monetary | required, >= 0 |
| duration | Integer | minutes, > 0 |
| active | Boolean | default True |

**`carwash.vehicle`**
| Field | Type | Notes |
|-------|------|-------|
| plate_number | Char | required, unique (normalized upper-case, no spaces) |
| make | Char | |
| model | Char | |
| owner_id | Many2one `res.partner` | required |
| booking_ids | One2many | inverse of booking.vehicle_id |
| booking_count | Integer (computed) | number of bookings per vehicle |

**`carwash.booking`** (inherits `mail.thread` for chatter)
| Field | Type | Notes |
|-------|------|-------|
| name | Char | sequence, e.g. `CW/00001` |
| customer_id | Many2one `res.partner` | required |
| vehicle_id | Many2one `carwash.vehicle` | required, must belong to customer |
| service_id | Many2one `carwash.service` | required |
| scheduled_date | Datetime | required, not in the past on create |
| price | Monetary | computed from service, stored, overridable by Manager |
| state | Selection | see 2.2, tracked |
| invoice_id | Many2one `account.move` | set when Done, read-only |

**`res.partner` extension**
| Field | Type | Notes |
|-------|------|-------|
| vehicle_ids | One2many | |
| booking_ids | One2many | |
| total_revenue | Monetary (computed) | sum of posted invoice totals from bookings |

### 2.2 Booking state machine

```
Draft ──confirm──> Confirmed ──start──> In Progress ──done──> Done
  │                    │                     │
  └──────────────── cancel (Manager only) ───┘──────> Cancelled
```

| From | Action | To | Who |
|------|--------|----|-----|
| Draft | Confirm | Confirmed | Staff, Manager |
| Confirmed | Start | In Progress | Staff, Manager |
| In Progress | Mark Done | Done | Staff, Manager |
| Draft / Confirmed / In Progress | Cancel | Cancelled | Manager |

* Done and Cancelled are terminal.
* Any other transition raises `UserError`.
* Every transition is posted to the chatter.

### 2.3 Business rules
* **Pricing:** `price` defaults to `service.price`. Only a Manager may change it after creation. Later service price changes do not alter existing bookings.
* **Cancellation:** Manager only. A Done booking cannot be cancelled (issue a credit note in Odoo instead).
* **Invoice generation:** on Done, create a customer invoice (`account.move`, type `out_invoice`) with one line for the service at the booking price, post it, and store it in `invoice_id`. Running Done twice never creates a second invoice.
* **Ownership:** the vehicle's owner must match the booking customer.
* **Plate number:** globally unique.

### 2.4 Users and access rights

| Group | Can do |
|-------|--------|
| Car Wash / Staff | Create and read bookings, vehicles, services; Confirm, Start, Mark Done. Cannot cancel or override price. |
| Car Wash / Manager | Everything Staff can, plus cancel, override price, edit services, delete records. Implies Staff. |
| `sentra_agent` (API user) | Read-only on bookings, vehicles, services, partners, invoices. No write, create, or unlink on any model. |

---

## 3. Incident Types (SRE agent)

| # | Incident | Alert | Typical evidence | Candidate fix (needs approval) |
|---|----------|-------|------------------|-------------------------------|
| 1 | Odoo container down | `OdooDown` | container exited, last log lines | `restart_service(odoo)` |
| 2 | PostgreSQL container down | `OdooDown` + DB exporter down | db container status, db logs | `restart_service(db)` |
| 3 | Odoo slow | `OdooHighLatency` | blackbox latency, slow queries, CPU | `clear_odoo_cache()` or `kill_long_running_query(pid)` |
| 4 | DB connections near limit | `PostgresConnectionsHigh` | `pg_stat_activity`, idle-in-transaction | `kill_long_running_query(pid)` |
| 5 | Long blocking query | `OdooHighLatency` / locks | `pg_stat_activity`, lock waits | `kill_long_running_query(pid)` |
| 6 | Container memory high | `ContainerMemoryHigh` | cAdvisor memory, restarts | `restart_service(service)` |
| 7 | Python error in custom module | `OdooDown` or HTTP 500s | traceback in Odoo logs | none; report diagnosis only (requires code fix) |

Rule: when no safe action exists, the agent diagnoses and escalates; it never improvises.

## 4. Business Agent Questions

1. What was revenue this week?
2. Which invoices are unpaid?
3. How many bookings are scheduled tomorrow?
4. Who are the top 5 customers?
5. Which service is most popular this month?

Anything outside this set is attempted only with read-only `odoo_search`; if the data is not available, the agent states it does not know.

---

## 5. Design Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| ERP | Odoo 17 Community | Real ERP, realistic failure modes, custom module demonstrates domain work. |
| LLM | Anthropic API with tool calling | Native tool-use loop, no framework needed. |
| Agent service | FastAPI (Python) | Webhook receiver + small API. |
| Human interface | Web UI served by the agent service (`/ui`) | No external accounts, self-contained demo, live incident view with Approve/Reject buttons. |
| Monitoring | Prometheus, Alertmanager, Grafana, Blackbox, postgres_exporter, cAdvisor | Standard stack; every alert has a concrete source. |
| Safety model | Read tools free, action tools gated by human approval | Least privilege; no unattended changes. |

## 6. Open Questions
None. Coding can begin from this document and `ARCHITECTURE.md`.

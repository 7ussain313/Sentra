"""Seed demo data for the Sentra car wash.

Run inside the Odoo container (see README / scripts/seed.ps1):

    odoo shell -d sentra --no-http < scripts/seed.py

Idempotent: every record is looked up before it is created, and bookings are
only seeded when none exist. Secrets generated for new users are printed once
as `SEED_*=` lines so the caller can store them in `.env`.
"""
import random
import secrets
from datetime import timedelta

from odoo import fields

rnd = random.Random(42)
now = fields.Datetime.now()
today = fields.Date.context_today(env["res.users"])

Partner = env["res.partner"]
Service = env["carwash.service"]
Vehicle = env["carwash.vehicle"]
Booking = env["carwash.booking"]
Users = env["res.users"]
out = []  # lines printed at the end


def get_or_create(model, domain, vals):
    rec = model.search(domain, limit=1)
    return rec or model.create(vals)


# ---------------------------------------------------------------- services
SERVICES = [
    ("Basic Wash", 15.0, 20),
    ("Full Wash", 30.0, 45),
    ("Interior Cleaning", 45.0, 60),
    ("Wax & Polish", 60.0, 90),
]
services = [
    get_or_create(Service, [("name", "=", n)], {"name": n, "price": p, "duration": d})
    for n, p, d in SERVICES
]

# ------------------------------------------------------ customers + vehicles
CUSTOMERS = [
    ("Alice Johnson", [("KAB 101A", "Toyota", "Corolla")]),
    ("Bilal Khan", [("LHR 2024", "Honda", "Civic"), ("LHR 7788", "Suzuki", "Swift")]),
    ("Carla Gomez", [("CGZ 330", "Ford", "Focus")]),
    ("David Okafor", [("DOK 555", "Nissan", "Altima")]),
    ("Emma Schmidt", [("ESC 900", "BMW", "320i"), ("ESC 901", "Audi", "A4")]),
    ("Farid Al-Sayed", [("FAS 042", "Kia", "Sportage")]),
    ("Grace Lee", [("GLE 612", "Hyundai", "Elantra")]),
    ("Hiro Tanaka", [("HTN 808", "Mazda", "CX-5")]),
]
customers, vehicles = [], []
for name, plates in CUSTOMERS:
    c = get_or_create(Partner, [("name", "=", name)], {"name": name})
    customers.append(c)
    for plate, make, model in plates:
        norm = plate.replace(" ", "").upper()
        vehicles.append(get_or_create(
            Vehicle, [("plate_number", "=", norm)],
            {"plate_number": norm, "make": make, "model": model, "owner_id": c.id},
        ))

# ------------------------------------------------------------ bookings
def make_booking(vehicle, service, when, state):
    """Create a booking and walk it through the real workflow up to `state`."""
    b = Booking.create({
        "customer_id": vehicle.owner_id.id,
        "vehicle_id": vehicle.id,
        "service_id": service.id,
        "scheduled_date": now + timedelta(days=1),  # create-time rule: not in the past
    })
    if state == "cancelled":
        b.action_cancel()
    elif state in ("confirmed", "in_progress", "done"):
        b.action_confirm()
        if state in ("in_progress", "done"):
            b.action_start()
        if state == "done":
            b.action_done()
    b.scheduled_date = when  # history is allowed after creation
    return b


def backdate_invoice(booking, when):
    inv = booking.invoice_id
    inv.button_draft()
    inv.invoice_date = when.date()
    inv.action_post()


def pay(invoice, when):
    wiz = env["account.payment.register"].with_context(
        active_model="account.move", active_ids=invoice.ids
    ).create({"payment_date": when.date()})
    wiz.action_create_payments()


created = {"draft": 0, "confirmed": 0, "in_progress": 0, "done": 0, "cancelled": 0}
paid = unpaid = 0
if not Booking.search_count([]):
    # Completed history: last 21 days, ~4 per week-day cluster; most paid.
    for i in range(18):
        v = rnd.choice(vehicles)
        s = rnd.choice(services)
        when = now - timedelta(days=rnd.randint(0, 20), hours=rnd.randint(0, 8))
        b = make_booking(v, s, when, "done")
        backdate_invoice(b, when)
        created["done"] += 1
        if i % 4 != 3:  # ~25% stay unpaid
            pay(b.invoice_id, when)
            paid += 1
        else:
            unpaid += 1
    # Cancelled history.
    for _ in range(2):
        make_booking(rnd.choice(vehicles), rnd.choice(services),
                     now - timedelta(days=rnd.randint(1, 10)), "cancelled")
        created["cancelled"] += 1
    # Today: one in progress, one confirmed.
    make_booking(vehicles[0], services[1], now, "in_progress"); created["in_progress"] += 1
    make_booking(vehicles[2], services[0], now + timedelta(hours=2), "confirmed"); created["confirmed"] += 1
    # Tomorrow and later: confirmed + draft.
    for k, (state, days) in enumerate([("confirmed", 1), ("confirmed", 1), ("draft", 1),
                                       ("draft", 2), ("confirmed", 3)]):
        make_booking(vehicles[(k + 3) % len(vehicles)], services[k % len(services)],
                     now + timedelta(days=days, hours=k), state)
        created[state] += 1

# ------------------------------------------------------------ users
def ensure_user(login, name, group_xmlids, env_key):
    user = Users.search([("login", "=", login)], limit=1)
    if user:
        return user, None
    password = secrets.token_urlsafe(12)
    groups = [env.ref(x).id for x in group_xmlids]
    user = Users.with_context(no_reset_password=True).create({
        "name": name, "login": login, "password": password,
        "email": "%s@sentra.local" % login, "groups_id": [(6, 0, groups)],
    })
    out.append("%s=%s" % (env_key, password))
    return user, password


ensure_user("manager", "Demo Manager", ["carwash.group_manager"], "SEED_MANAGER_PASSWORD")
ensure_user("staff", "Demo Staff", ["carwash.group_staff"], "SEED_STAFF_PASSWORD")
agent, _pw = ensure_user("sentra_agent", "Sentra Agent", ["carwash.group_agent_readonly"],
                         "SEED_AGENT_PASSWORD")
# The agent authenticates with an API key, never with its password.
if not env["res.users.apikeys"].sudo().search_count([("user_id", "=", agent.id)]):
    key = env["res.users.apikeys"].with_user(agent)._generate(None, "sentra-agent")
    out.append("ODOO_AGENT_API_KEY=%s" % key)

env.cr.commit()
print("SEED_SUMMARY", "services=%d customers=%d vehicles=%d bookings=%d paid=%d unpaid=%d states=%s" % (
    len(services), len(customers), len(vehicles), Booking.search_count([]), paid, unpaid, created))
for line in out:
    print(line)

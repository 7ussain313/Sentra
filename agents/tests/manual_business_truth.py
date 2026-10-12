"""Check the business agent's tool layer against independent SQL ground truth.

Calls exactly the tool queries a model should issue for the five supported
questions (through the real registry, as the read-only agent user) and compares
them with SQL run as the database owner. This validates the data path and the
definitions in the system prompt; it does not test model reasoning.

Run inside the agents container:  python tests/manual_business_truth.py
"""
import os
from datetime import date, timedelta

import psycopg2

from app.tools import call

today = date.today()
monday = today - timedelta(days=today.weekday())
sunday = monday + timedelta(days=6)
tomorrow = today + timedelta(days=1)
month_start = today.replace(day=1)
next_month = (month_start + timedelta(days=32)).replace(day=1)

db = psycopg2.connect(host="db", dbname=os.environ["ODOO_DB_NAME"], user=os.environ["POSTGRES_USER"],
                      password=os.environ["POSTGRES_PASSWORD"])
cur = db.cursor()
failures = 0


def check(label, tool_value, sql_value):
    global failures
    ok = tool_value == sql_value
    failures += 0 if ok else 1
    print(f"[{'OK ' if ok else 'FAIL'}] {label}\n      tool={tool_value}\n      sql ={sql_value}")


INV = [["move_type", "=", "out_invoice"], ["state", "=", "posted"]]

# 1. revenue this week
r = call("odoo_aggregate", {"model": "account.move", "aggregates": ["amount_total:sum"],
                            "domain": INV + [["invoice_date", ">=", str(monday)],
                                             ["invoice_date", "<=", str(sunday)]]},
         incident_id="truth", actor="business-agent")
tool = round(r["groups"][0].get("amount_total") or 0.0, 2) if r["groups"] else 0.0
cur.execute("select coalesce(sum(amount_total),0) from account_move where move_type='out_invoice' "
            "and state='posted' and invoice_date between %s and %s", (monday, sunday))
check(f"revenue this week ({monday}..{sunday})", tool, float(cur.fetchone()[0]))

# 2. unpaid invoices
r = call("odoo_search", {"model": "account.move", "limit": 100,
                         "domain": INV + [["payment_state", "in", ["not_paid", "partial"]]],
                         "fields": ["name", "partner_id", "amount_total", "amount_residual"]},
         incident_id="truth", actor="business-agent")
tool = sorted((x["name"], round(x["amount_residual"], 2)) for x in r["records"])
cur.execute("select name, amount_residual from account_move where move_type='out_invoice' and "
            "state='posted' and payment_state in ('not_paid','partial') order by name")
check("unpaid invoices (name, amount owed)", tool, sorted((n, round(float(a), 2)) for n, a in cur.fetchall()))

# 3. bookings scheduled tomorrow
r = call("odoo_aggregate", {"model": "carwash.booking", "aggregates": ["id:count"],
                            "domain": [["state", "in", ["draft", "confirmed", "in_progress"]],
                                       ["scheduled_date", ">=", f"{tomorrow} 00:00:00"],
                                       ["scheduled_date", "<", f"{tomorrow + timedelta(days=1)} 00:00:00"]]},
         incident_id="truth", actor="business-agent")
tool = r["groups"][0]["__count"] if r["groups"] else 0
cur.execute("select count(*) from carwash_booking where state in ('draft','confirmed','in_progress') "
            "and scheduled_date >= %s and scheduled_date < %s", (f"{tomorrow} 00:00", f"{tomorrow + timedelta(days=1)} 00:00"))
check(f"bookings scheduled tomorrow ({tomorrow})", tool, cur.fetchone()[0])

# 4. top 5 customers by invoiced amount
r = call("odoo_aggregate", {"model": "account.move", "domain": INV, "group_by": ["partner_id"],
                            "aggregates": ["amount_total:sum"], "order_by": "amount_total desc", "limit": 5},
         incident_id="truth", actor="business-agent")
tool = [(g["partner_id"][1], round(g["amount_total"], 2)) for g in r["groups"]]
cur.execute("select p.name, sum(m.amount_total) t from account_move m join res_partner p on p.id=m.partner_id "
            "where m.move_type='out_invoice' and m.state='posted' group by p.name order by t desc, p.name limit 5")
sql = [(n, round(float(t), 2)) for n, t in cur.fetchall()]
# equal totals may tie-break differently: compare the amounts in order, and the set of names per amount
same_amounts = [a for _, a in tool] == [a for _, a in sql]
cur.execute("select count(distinct m.partner_id) from account_move m where m.move_type='out_invoice' and m.state='posted'")
check("top 5 customers (amounts in order)", [a for _, a in tool], [a for _, a in sql])
print("      tool names:", [n for n, _ in tool])

# 5. most popular service this month (done bookings)
r = call("odoo_aggregate", {"model": "carwash.booking", "group_by": ["service_id"], "aggregates": ["id:count"],
                            "domain": [["state", "=", "done"], ["scheduled_date", ">=", f"{month_start} 00:00:00"],
                                       ["scheduled_date", "<", f"{next_month} 00:00:00"]]},
         incident_id="truth", actor="business-agent")
tool = sorted(((g["service_id"][1], g["__count"]) for g in r["groups"]), key=lambda x: (-x[1], x[0]))
cur.execute("select s.name, count(*) from carwash_booking b join carwash_service s on s.id=b.service_id "
            "where b.state='done' and b.scheduled_date >= %s and b.scheduled_date < %s group by s.name "
            "order by 2 desc, 1", (f"{month_start} 00:00", f"{next_month} 00:00"))
check(f"service popularity this month ({month_start}..)", tool, [(n, c) for n, c in cur.fetchall()])

# write attempts are impossible by design: the agent user is rejected by Odoo itself
import xmlrpc.client
key, login = os.environ["ODOO_AGENT_API_KEY"], os.environ["ODOO_AGENT_LOGIN"]
uid = xmlrpc.client.ServerProxy("http://odoo:8069/xmlrpc/2/common").authenticate(
    os.environ["ODOO_DB_NAME"], login, key, {})
rpc = xmlrpc.client.ServerProxy("http://odoo:8069/xmlrpc/2/object")
for model, method, args in [("carwash.booking", "create", [{}]), ("res.partner", "write", [[1], {"name": "x"}]),
                            ("account.move", "unlink", [[1]]), ("carwash.service", "write", [[1], {"price": 1}])]:
    try:
        rpc.execute_kw(os.environ["ODOO_DB_NAME"], uid, key, model, method, args)
        print(f"[FAIL] {model}.{method} was allowed for the agent user"); failures += 1
    except xmlrpc.client.Fault:
        print(f"[OK ] {model}.{method} denied by Odoo for the agent user")

print("\nRESULT:", "ALL CHECKS PASSED" if not failures else f"{failures} FAILURE(S)")
raise SystemExit(1 if failures else 0)

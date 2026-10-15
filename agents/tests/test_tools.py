"""Offline tests for the tool layer's safety rules (no Docker, DB or Odoo needed)."""
import json

import pytest

from app import audit
from app.config import get_settings
from app.tools import registry
from app.tools.base import ApprovalRequired, ToolError
from app.tools.database import validate_select
from app.tools.odoo import validate_domain


@pytest.fixture(autouse=True)
def audit_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_DIR", str(tmp_path))
    get_settings.cache_clear()
    registry.set_approval_checker(lambda *_: False)
    yield tmp_path
    get_settings.cache_clear()


def audit_lines(path):
    f = path / "audit.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


# ---------------------------------------------------------------- SQL guard
@pytest.mark.parametrize("sql", [
    "SELECT 1",
    "select pid, state from pg_stat_activity where state = 'active';",
    "SELECT count(*) FROM pg_locks WHERE NOT granted",
    "select 'update' as word, \"delete\" from t",       # keywords only inside literals/identifiers
    "SELECT jsonb_set('{}'::jsonb, '{a}', '1')",
])
def test_select_allowed(sql):
    assert validate_select(sql).lower().startswith("select")


@pytest.mark.parametrize("sql", [
    "DROP TABLE res_partner",
    "DELETE FROM res_partner",
    "UPDATE res_partner SET name='x'",
    "INSERT INTO res_partner(name) VALUES ('x')",
    "SELECT 1; DROP TABLE res_partner",
    "SELECT 1; SELECT 2",
    "SELECT * INTO newtable FROM res_partner",
    "SELECT pg_terminate_backend(123)",
    "SELECT pg_sleep(100)",
    "SELECT set_config('a','b',false)",
    "SELECT nextval('base_cache_signaling_default')",
    "SELECT * FROM res_partner FOR UPDATE",
    "SELECT 1 -- comment",
    "SELECT /* hi */ 1",
    "SELECT $$x$$",
    "SELECT dblink('x','y')",
    "COPY res_partner TO '/tmp/x'",
    "WITH d AS (DELETE FROM res_partner RETURNING *) SELECT * FROM d",
    "  ",
    "EXPLAIN SELECT 1",
    "SET ROLE postgres",
])
def test_select_rejected(sql):
    with pytest.raises(ToolError):
        validate_select(sql)


def test_sql_too_long():
    with pytest.raises(ToolError):
        validate_select("SELECT " + "1," * 2000 + "1")


# ------------------------------------------------------------ Odoo domain
def test_domain_ok():
    d = validate_domain(["|", ["state", "=", "done"], ["partner_id.name", "ilike", "a"]])
    assert d[0] == "|" and d[1] == ["state", "=", "done"]


def test_domain_string_terms_are_parsed():
    d = validate_domain(["scheduled_date >= 2026-10-16 00:00:00", "state = 'done'", "price > 10",
                         "active = true"])
    assert d == [["scheduled_date", ">=", "2026-10-16 00:00:00"], ["state", "=", "done"],
                 ["price", ">", 10], ["active", "=", True]]


@pytest.mark.parametrize("term", ["state; drop table x", "__import__('os') = 1", "state =~ x",
                                  "id in [1, 2]", "just words"])
def test_domain_bad_string_terms_rejected(term):
    with pytest.raises(ToolError):
        validate_domain([term])


@pytest.mark.parametrize("domain", [
    [["state", "=~", "x"]],
    [["state; drop", "=", "x"]],
    [["state", "=", {"a": 1}]],
    [["state", "="]],
    ["XOR"],
    [["a", "=", 1]] * 21,
    [["id", "in", [1] * 101]],
])
def test_domain_rejected(domain):
    with pytest.raises(ToolError):
        validate_domain(domain)


# ----------------------------------------------------- registry + audit
def test_unknown_tool_rejected_and_audited(audit_dir):
    with pytest.raises(ToolError):
        registry.call("rm_rf", {})
    assert audit_lines(audit_dir)[-1]["status"] == "rejected"


@pytest.mark.parametrize("name,args", [
    ("read_logs", {"service": "agents", "lines": 10}),      # not allowlisted
    ("read_logs", {"service": "odoo", "lines": 5000}),      # out of range
    ("read_logs", {"service": "odoo", "lines": 10, "x": 1}),  # unknown field
    ("odoo_search", {"model": "res.users", "fields": ["login"]}),
    ("odoo_search", {"model": "ir.config_parameter"}),
    ("odoo_search", {"model": "carwash.booking", "fields": ["name; x"]}),
    ("odoo_search", {"model": "carwash.booking", "limit": 10_000}),
    ("query_database", {"query": ""}),
    ("query_metrics", {"promql": ""}),
    ("restart_service", {"service": "grafana"}),
    ("kill_long_running_query", {"pid": "1; DROP"}),
    ("kill_long_running_query", {"pid": 1}),
])
def test_invalid_input_rejected(name, args, audit_dir):
    with pytest.raises(ToolError):
        registry.call(name, args, approval_id="a1")
    assert audit_lines(audit_dir)[-1]["status"] == "rejected"


def test_unsafe_sql_rejected_through_registry(audit_dir):
    with pytest.raises(ToolError):
        registry.call("query_database", {"query": "DROP TABLE res_partner"})
    last = audit_lines(audit_dir)[-1]
    assert last["tool"] == "query_database" and last["status"] == "rejected"


@pytest.mark.parametrize("name,args", [
    ("restart_service", {"service": "odoo"}),
    ("clear_odoo_cache", {}),
    ("kill_long_running_query", {"pid": 4242}),
])
def test_actions_blocked_without_approval(name, args, audit_dir):
    with pytest.raises(ApprovalRequired):
        registry.call(name, args)
    with pytest.raises(ApprovalRequired):
        registry.call(name, args, approval_id="forged-id")   # checker denies it
    assert [x["status"] for x in audit_lines(audit_dir)] == ["blocked", "blocked"]


def test_action_runs_only_when_checker_grants(audit_dir, monkeypatch):
    ran = []
    tool = registry.TOOLS["clear_odoo_cache"]
    monkeypatch.setitem(
        registry.TOOLS, "clear_odoo_cache",
        type(tool)(tool.name, tool.description, tool.model, lambda p: ran.append(1) or {"success": True}, "action"),
    )
    registry.set_approval_checker(lambda aid, name, args: aid == "good" and name == "clear_odoo_cache")
    with pytest.raises(ApprovalRequired):
        registry.call("clear_odoo_cache", {}, approval_id="bad")
    assert not ran
    assert registry.call("clear_odoo_cache", {}, approval_id="good", incident_id="inc-1") == {"success": True}
    assert ran == [1]
    last = audit_lines(audit_dir)[-1]
    assert last["status"] == "ok" and last["approval_id"] == "good" and last["incident_id"] == "inc-1"


def test_audit_redacts_secrets_and_truncates(audit_dir, monkeypatch):
    monkeypatch.setenv("SOME_API_KEY", "super-secret-value-123")
    audit.record(tool="t", input={"k": "super-secret-value-123"}, output="x" * 5000, status="ok")
    line = (audit_dir / "audit.jsonl").read_text()
    assert "super-secret-value-123" not in line
    assert "[REDACTED]" in line and "truncated" in line


def test_classification_and_schemas():
    assert set(registry.READ_TOOLS) == {
        "read_logs", "check_container_status", "query_metrics", "query_database", "odoo_search",
        "odoo_aggregate"}
    assert set(registry.ACTION_TOOLS) == {"restart_service", "clear_odoo_cache", "kill_long_running_query"}
    names = {s["name"] for s in registry.schemas()}
    assert names == set(registry.TOOLS)
    assert {s["name"] for s in registry.schemas(registry.READ_TOOLS)} == set(registry.READ_TOOLS)

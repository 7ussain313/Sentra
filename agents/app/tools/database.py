import re
from typing import Any

import psycopg2
from pydantic import Field

from app.config import get_settings
from app.tools.base import StrictInput, Tool, ToolError

MAX_ROWS = 100
MAX_SQL_CHARS = 2000

_STRING = re.compile(r"'(?:[^']|'')*'")
_QUOTED_IDENT = re.compile(r'"(?:[^"]|"")*"')
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|call|do|"
    r"execute|prepare|set|reset|vacuum|analyze|lock|listen|notify|unlisten|into|merge|"
    r"refresh|reindex|cluster|comment|security|discard|load|import|"
    r"pg_terminate_backend|pg_cancel_backend|pg_sleep|pg_read_file|pg_read_binary_file|"
    r"pg_ls_dir|pg_ls_logdir|lo_import|lo_export|lo_put|dblink\w*|set_config|"
    r"pg_reload_conf|pg_rotate_logfile|nextval|setval|pg_advisory\w*)\b"
    r"|\bfor\s+(update|share|no\s+key|key\s+share)\b",
    re.IGNORECASE,
)


def validate_select(sql: str) -> str:
    """Return a cleaned single SELECT statement or raise ToolError.

    This is the first of several layers; the connection is also a read-only
    transaction made by a role that has no table privileges.
    """
    if not isinstance(sql, str) or not sql.strip():
        raise ToolError("Empty query")
    if len(sql) > MAX_SQL_CHARS:
        raise ToolError(f"Query too long (max {MAX_SQL_CHARS} characters)")
    s = sql.strip()
    if "--" in s or "/*" in s or "*/" in s:
        raise ToolError("SQL comments are not allowed")
    if "$" in s or "\\" in s:
        raise ToolError("Dollar quoting and backslashes are not allowed")
    if s.endswith(";"):
        s = s[:-1].rstrip()
    bare = _QUOTED_IDENT.sub('""', _STRING.sub("''", s))
    if ";" in bare:
        raise ToolError("Only a single statement is allowed")
    if not re.match(r"^select\b", bare, re.IGNORECASE):
        raise ToolError("Only SELECT statements are allowed")
    bad = _FORBIDDEN.search(bare)
    if bad:
        raise ToolError(f"Forbidden keyword or function in query: {bad.group(0).strip()}")
    return s


class QueryDatabaseInput(StrictInput):
    query: str = Field(..., min_length=1, max_length=MAX_SQL_CHARS)


def _connect():
    cfg = get_settings()
    return psycopg2.connect(
        host=cfg.db_host,
        port=cfg.db_port,
        dbname=cfg.odoo_db_name,
        user="sentra_readonly",
        password=cfg.agent_db_ro_password,
        connect_timeout=5,
        application_name="sentra-agent-readonly",
        options="-c default_transaction_read_only=on -c statement_timeout=5000",
    )


def query_database(p: QueryDatabaseInput) -> dict[str, Any]:
    sql = validate_select(p.query)
    try:
        conn = _connect()
    except psycopg2.Error as e:
        raise ToolError(f"Database is not reachable: {str(e).splitlines()[0]}") from e
    try:
        conn.set_session(readonly=True, autocommit=False)
        # Server-side cursor: never pulls an unbounded result into memory.
        with conn.cursor(name="sentra_q") as cur:
            cur.itersize = MAX_ROWS + 1
            try:
                cur.execute(sql)
                rows = cur.fetchmany(MAX_ROWS + 1)
                cols = [d[0] for d in cur.description]
            except psycopg2.Error as e:
                raise ToolError(f"Query failed: {str(e).splitlines()[0]}") from e
        return {
            "columns": cols,
            "rows": [dict(zip(cols, r)) for r in rows[:MAX_ROWS]],
            "truncated": len(rows) > MAX_ROWS,
        }
    finally:
        conn.rollback()
        conn.close()


TOOL = Tool(
    name="query_database",
    description=(
        "Run ONE read-only SELECT against PostgreSQL diagnostics (pg_stat_activity, pg_locks, "
        "pg_stat_* views, catalogs). Returns at most 100 rows. No business table data."
    ),
    model=QueryDatabaseInput,
    fn=query_database,
    kind="read",
)

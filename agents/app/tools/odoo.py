import re
import xmlrpc.client
from typing import Any

from pydantic import Field, field_validator

from app.config import get_settings
from app.tools.base import StrictInput, Tool, ToolError

ALLOWED_MODELS_EXACT = {"res.partner", "account.move"}
MODEL_RE = re.compile(r"^carwash\.[a-z_]+(\.[a-z_]+)*$")
FIELD_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
PATH_RE = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)*$")
OPERATORS = {"=", "!=", "<", "<=", ">", ">=", "in", "not in", "like", "ilike",
             "not like", "not ilike", "=like", "=ilike"}
LOGIC = {"&", "|", "!"}
MAX_OUTPUT_CHARS = 30_000

_uid_cache: dict[tuple[str, str], int] = {}


def _scalar_ok(v: Any) -> bool:
    return v is None or isinstance(v, (str, int, float, bool))


def validate_domain(domain: list) -> list:
    if len(domain) > 20:
        raise ToolError("Domain too long (max 20 terms)")
    out: list = []
    for term in domain:
        if isinstance(term, str):
            if term not in LOGIC:
                raise ToolError(f"Invalid domain operator: {term!r}")
            out.append(term)
            continue
        if not (isinstance(term, (list, tuple)) and len(term) == 3):
            raise ToolError("Each domain term must be [field, operator, value]")
        f, op, v = term
        if not (isinstance(f, str) and PATH_RE.match(f)):
            raise ToolError(f"Invalid field name in domain: {f!r}")
        if op not in OPERATORS:
            raise ToolError(f"Operator not allowed: {op!r}")
        if isinstance(v, (list, tuple)):
            if len(v) > 100 or not all(_scalar_ok(x) for x in v):
                raise ToolError("Invalid list value in domain")
        elif not _scalar_ok(v):
            raise ToolError("Invalid value in domain")
        out.append([f, op, list(v) if isinstance(v, tuple) else v])
    return out


def _check_model(v: str) -> str:
    if v in ALLOWED_MODELS_EXACT or MODEL_RE.match(v):
        return v
    raise ValueError(f"model not in allowlist: {v!r}")


class OdooSearchInput(StrictInput):
    model: str
    domain: list = Field(default_factory=list)
    fields: list[str] = Field(default_factory=lambda: ["display_name"], min_length=1, max_length=30)
    limit: int = Field(20, ge=1, le=100)

    @field_validator("model")
    @classmethod
    def _model_allowed(cls, v: str) -> str:
        return _check_model(v)

    @field_validator("fields")
    @classmethod
    def _fields_ok(cls, v: list[str]) -> list[str]:
        for f in v:
            if not FIELD_RE.match(f):
                raise ValueError(f"invalid field name: {f!r}")
        return v


def _uid(url: str, db: str, login: str, key: str) -> int:
    ck = (url, login)
    if ck not in _uid_cache:
        uid = xmlrpc.client.ServerProxy(url + "/xmlrpc/2/common").authenticate(db, login, key, {})
        if not uid:
            raise ToolError("Odoo rejected the agent credentials")
        _uid_cache[ck] = uid
    return _uid_cache[ck]


def odoo_search(p: OdooSearchInput) -> dict:
    cfg = get_settings()
    domain = validate_domain(p.domain)
    if not cfg.odoo_agent_api_key:
        raise ToolError("ODOO_AGENT_API_KEY is not configured")
    url = cfg.odoo_url.rstrip("/")
    try:
        uid = _uid(url, cfg.odoo_db_name, cfg.odoo_agent_login, cfg.odoo_agent_api_key)
        rpc = xmlrpc.client.ServerProxy(url + "/xmlrpc/2/object", allow_none=True)
        # The method is fixed: this tool can only ever search_read.
        records = rpc.execute_kw(
            cfg.odoo_db_name, uid, cfg.odoo_agent_api_key, p.model, "search_read",
            [domain], {"fields": p.fields, "limit": p.limit},
        )
    except xmlrpc.client.Fault as e:
        raise ToolError(f"Odoo error: {e.faultString.strip().splitlines()[-1][:300]}") from e
    except (OSError, xmlrpc.client.ProtocolError) as e:
        _uid_cache.clear()
        raise ToolError(f"Odoo is not reachable: {e}") from e
    truncated = len(str(records)) > MAX_OUTPUT_CHARS
    while records and len(str(records)) > MAX_OUTPUT_CHARS:
        records = records[: len(records) // 2]
    return {"model": p.model, "count": len(records), "truncated": truncated, "records": records}


TOOL = Tool(
    name="odoo_search",
    description=(
        "Read Odoo records (search_read only) through the read-only agent user. Models: "
        "carwash.*, res.partner, account.move. Domain is a list of [field, operator, value]."
    ),
    model=OdooSearchInput,
    fn=odoo_search,
    kind="read",
)


# ---------------------------------------------------------------- aggregates
GROUP_RE = re.compile(r"^[a-z_][a-z0-9_]*(:(day|week|month|quarter|year))?$")
AGG_RE = re.compile(r"^[a-z_][a-z0-9_]*:(sum|avg|min|max|count|count_distinct)$")
ORDER_RE = re.compile(r"^[a-z_][a-z0-9_:]*( (asc|desc))?(, [a-z_][a-z0-9_:]*( (asc|desc))?)*$")


class OdooAggregateInput(StrictInput):
    model: str
    domain: list = Field(default_factory=list)
    group_by: list[str] = Field(default_factory=list, max_length=3)
    aggregates: list[str] = Field(default_factory=list, max_length=6)
    order_by: str | None = Field(None, max_length=120)
    limit: int = Field(20, ge=1, le=100)

    @field_validator("model")
    @classmethod
    def _model_allowed(cls, v: str) -> str:
        return _check_model(v)

    @field_validator("group_by")
    @classmethod
    def _group_ok(cls, v: list[str]) -> list[str]:
        for g in v:
            if not GROUP_RE.match(g):
                raise ValueError(f"invalid group_by: {g!r}")
        return v

    @field_validator("aggregates")
    @classmethod
    def _agg_ok(cls, v: list[str]) -> list[str]:
        for a in v:
            if not AGG_RE.match(a):
                raise ValueError(f"invalid aggregate (use field:sum|avg|min|max|count|count_distinct): {a!r}")
        return v

    @field_validator("order_by")
    @classmethod
    def _order_ok(cls, v: str | None) -> str | None:
        if v is not None and not ORDER_RE.match(v):
            raise ValueError(f"invalid order_by: {v!r}")
        return v


def odoo_aggregate(p: OdooAggregateInput) -> dict:
    cfg = get_settings()
    domain = validate_domain(p.domain)
    if not cfg.odoo_agent_api_key:
        raise ToolError("ODOO_AGENT_API_KEY is not configured")
    if not p.group_by and not p.aggregates:
        raise ToolError("Give at least one group_by or aggregate")
    url = cfg.odoo_url.rstrip("/")
    kwargs: dict[str, Any] = {"lazy": False, "limit": p.limit}
    if p.order_by:
        kwargs["orderby"] = p.order_by
    try:
        uid = _uid(url, cfg.odoo_db_name, cfg.odoo_agent_login, cfg.odoo_agent_api_key)
        rpc = xmlrpc.client.ServerProxy(url + "/xmlrpc/2/object", allow_none=True)
        # Fixed method: aggregation only, never a write.
        groups = rpc.execute_kw(
            cfg.odoo_db_name, uid, cfg.odoo_agent_api_key, p.model, "read_group",
            [domain, p.aggregates or ["id:count"], p.group_by], kwargs,
        )
    except xmlrpc.client.Fault as e:
        raise ToolError(f"Odoo error: {e.faultString.strip().splitlines()[-1][:300]}") from e
    except (OSError, xmlrpc.client.ProtocolError) as e:
        _uid_cache.clear()
        raise ToolError(f"Odoo is not reachable: {e}") from e
    clean = [{k: v for k, v in g.items() if not k.startswith("__") or k == "__count"}
             for g in groups]
    return {"model": p.model, "count": len(clean), "groups": clean}


AGG_TOOL = Tool(
    name="odoo_aggregate",
    description=(
        "Read-only aggregation in Odoo (read_group): sum/avg/min/max/count, optionally grouped. "
        "aggregates like 'amount_total:sum'; group_by like 'partner_id' or 'scheduled_date:day'. "
        "Same model allowlist and domain format as odoo_search. Prefer this over summing records yourself."
    ),
    model=OdooAggregateInput,
    fn=odoo_aggregate,
    kind="read",
)

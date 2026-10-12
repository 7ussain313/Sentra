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


class OdooSearchInput(StrictInput):
    model: str
    domain: list = Field(default_factory=list)
    fields: list[str] = Field(default_factory=lambda: ["display_name"], min_length=1, max_length=30)
    limit: int = Field(20, ge=1, le=100)

    @field_validator("model")
    @classmethod
    def _model_allowed(cls, v: str) -> str:
        if v in ALLOWED_MODELS_EXACT or MODEL_RE.match(v):
            return v
        raise ValueError(f"model not in allowlist: {v!r}")

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

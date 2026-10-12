"""Tool registry: schemas, read/action classification and the single execution path.

Every tool call goes through `call()`, which validates input, enforces the
approval gate for action tools, and writes the audit record.
"""
import time
from typing import Any, Callable

from pydantic import ValidationError

from app import audit
from app.tools import actions, containers, database, logs, metrics, odoo
from app.tools.base import ApprovalRequired, Tool, ToolError

_ALL: list[Tool] = [
    logs.TOOL,
    containers.TOOL,
    metrics.TOOL,
    database.TOOL,
    odoo.TOOL,
    actions.RESTART,
    actions.CLEAR_CACHE,
    actions.KILL_QUERY,
]
TOOLS: dict[str, Tool] = {t.name: t for t in _ALL}
READ_TOOLS = [t.name for t in _ALL if t.kind == "read"]
ACTION_TOOLS = [t.name for t in _ALL if t.kind == "action"]

# (approval_id, tool_name, validated_args) -> granted?  Default: deny everything.
# The approval flow (web UI) installs the real checker; tests may install a fake.
ApprovalChecker = Callable[[str, str, dict[str, Any]], bool]
_checker: ApprovalChecker = lambda approval_id, name, args: False


def set_approval_checker(checker: ApprovalChecker) -> None:
    global _checker
    _checker = checker


def schemas(names: list[str] | None = None) -> list[dict[str, Any]]:
    """Tool definitions in the Anthropic Messages API `tools` format."""
    out = []
    for t in _ALL:
        if names is not None and t.name not in names:
            continue
        schema = t.model.model_json_schema()
        schema.pop("title", None)
        out.append({"name": t.name, "description": t.description, "input_schema": schema})
    return out


def _log(tool: str, kind: str, args: Any, status: str, started: float, **extra: Any) -> None:
    audit.record(
        tool=tool,
        kind=kind,
        input=args,
        status=status,
        duration_ms=round((time.monotonic() - started) * 1000),
        **extra,
    )


def call(
    name: str,
    args: dict[str, Any] | None = None,
    *,
    incident_id: str | None = None,
    actor: str = "agent",
    approval_id: str | None = None,
) -> Any:
    """Run a tool. Raises ToolError (or ApprovalRequired) on any refusal or failure."""
    started = time.monotonic()
    ctx = {"incident_id": incident_id, "actor": actor, "approval_id": approval_id}
    raw = args or {}

    tool = TOOLS.get(name)
    if tool is None:
        _log(name, "unknown", raw, "rejected", started, output="unknown tool", **ctx)
        raise ToolError(f"Unknown tool: {name}")

    try:
        params = tool.model.model_validate(raw)
    except ValidationError as e:
        msg = "; ".join(f"{'.'.join(map(str, x['loc'])) or 'input'}: {x['msg']}" for x in e.errors())
        _log(name, tool.kind, raw, "rejected", started, output=f"invalid input: {msg}", **ctx)
        raise ToolError(f"Invalid input for {name}: {msg}") from e

    if tool.kind == "action":
        granted = bool(approval_id) and _checker(approval_id, name, params.model_dump())
        if not granted:
            _log(name, tool.kind, raw, "blocked", started,
                 output="action requires a granted approval", **ctx)
            raise ApprovalRequired(f"{name} requires an approved request; none was granted")

    try:
        result = tool.fn(params)
    except ToolError as e:
        _log(name, tool.kind, raw, "rejected", started, output=str(e), **ctx)
        raise
    except Exception as e:  # unexpected: never leak a stack trace to the model
        _log(name, tool.kind, raw, "error", started, output=f"{type(e).__name__}: {e}", **ctx)
        raise ToolError(f"{name} failed unexpectedly") from e

    _log(name, tool.kind, raw, "ok", started, output=result, **ctx)
    return result

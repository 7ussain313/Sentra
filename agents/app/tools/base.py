from dataclasses import dataclass
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict


class ToolError(Exception):
    """A tool refused or failed. The message is safe to show to the model."""


class ApprovalRequired(ToolError):
    """An action tool was called without a granted approval."""


class StrictInput(BaseModel):
    """Base for tool inputs: unknown fields are rejected, not ignored."""

    model_config = ConfigDict(extra="forbid")


# The only services the agent may read logs of or restart.
ServiceName = Literal["odoo", "db"]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    model: type[StrictInput]
    fn: Callable[[Any], Any]
    kind: Literal["read", "action"]


def truncate_text(text: str, limit: int, keep: Literal["head", "tail"] = "tail") -> str:
    if len(text) <= limit:
        return text
    cut = len(text) - limit
    if keep == "tail":
        return f"[...{cut} chars truncated...]\n" + text[-limit:]
    return text[:limit] + f"\n[...{cut} chars truncated...]"

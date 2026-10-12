"""Pending-approval store for action tools.

An action tool runs only when a human approved that exact tool and argument set.
Approvals are single-use and expire. The web UI (Phase 8) calls `decide()`.
"""
import threading
import uuid
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta, timezone
from typing import Any

from app import audit
from app.config import get_settings


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Approval:
    id: str
    incident_id: str | None
    tool: str
    args: dict[str, Any]
    summary: str
    requested_at: str
    expires_at: str
    status: str = "pending"  # pending | approved | rejected | timeout
    decided_by: str | None = None
    decided_at: str | None = None
    used: bool = False
    _event: threading.Event = field(default_factory=threading.Event, repr=False, compare=False)

    def public(self) -> dict[str, Any]:
        # Not dataclasses.asdict(): it would try to deep-copy the threading.Event.
        return {f.name: getattr(self, f.name) for f in fields(self) if not f.name.startswith("_")}


class ApprovalStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, Approval] = {}

    def request(self, tool: str, args: dict[str, Any], incident_id: str | None,
                summary: str = "", timeout_seconds: int | None = None) -> Approval:
        timeout = timeout_seconds if timeout_seconds is not None else get_settings().approval_timeout_seconds
        now = _now()
        item = Approval(
            id=uuid.uuid4().hex[:12], incident_id=incident_id, tool=tool, args=args,
            summary=summary, requested_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=timeout)).isoformat(),
        )
        with self._lock:
            self._items[item.id] = item
        audit.record(kind="approval", status="requested", tool=tool, input=args,
                     incident_id=incident_id, approval_id=item.id)
        return item

    def get(self, approval_id: str) -> Approval | None:
        return self._items.get(approval_id)

    def pending(self) -> list[Approval]:
        with self._lock:
            return [a for a in self._items.values() if a.status == "pending"]

    def all(self) -> list[Approval]:
        with self._lock:
            return list(self._items.values())

    def decide(self, approval_id: str, approved: bool, user: str) -> Approval:
        """Single-use decision. Raises KeyError / ValueError for unknown or already-decided ids."""
        with self._lock:
            item = self._items.get(approval_id)
            if item is None:
                raise KeyError(approval_id)
            if item.status != "pending":
                raise ValueError(f"approval already {item.status}")
            if _now() > datetime.fromisoformat(item.expires_at):
                item.status = "timeout"
                item._event.set()
                raise ValueError("approval expired")
            item.status = "approved" if approved else "rejected"
            item.decided_by = user
            item.decided_at = _now().isoformat()
        item._event.set()
        audit.record(kind="approval", status=item.status, tool=item.tool, input=item.args,
                     incident_id=item.incident_id, approval_id=item.id, user=user)
        return item

    def wait(self, approval_id: str, timeout_seconds: float | None = None) -> str:
        """Block until decided or expired. Returns approved | rejected | timeout."""
        item = self._items[approval_id]
        if timeout_seconds is None:
            timeout_seconds = max(
                (datetime.fromisoformat(item.expires_at) - _now()).total_seconds(), 0)
        item._event.wait(timeout_seconds)
        with self._lock:
            if item.status == "pending":
                item.status = "timeout"
                item.decided_at = _now().isoformat()
                audit.record(kind="approval", status="timeout", tool=item.tool, input=item.args,
                             incident_id=item.incident_id, approval_id=item.id)
        return item.status

    def check(self, approval_id: str, tool: str, args: dict[str, Any]) -> bool:
        """Registry gate: approved, same tool and arguments, not used before. Consumes it."""
        with self._lock:
            item = self._items.get(approval_id)
            if (item is None or item.status != "approved" or item.used
                    or item.tool != tool or item.args != args):
                return False
            if _now() > datetime.fromisoformat(item.expires_at):
                return False
            item.used = True
            return True


store = ApprovalStore()

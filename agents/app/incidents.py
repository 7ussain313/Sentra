"""Incident store: in-memory index persisted as JSON files in incidents/."""
import json
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.audit import redact
from app.config import get_settings

OPEN_STATUSES = {"investigating", "awaiting_approval"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "alert"


class IncidentStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: dict[str, dict[str, Any]] = {}
        self._loaded_from: Path | None = None

    @property
    def directory(self) -> Path:
        d = get_settings().incidents_dir
        d.mkdir(parents=True, exist_ok=True)
        if self._loaded_from != d:
            self._load(d)
        return d

    def _load(self, d: Path) -> None:
        self._items = {}
        for f in sorted(d.glob("*.json")):
            try:
                inc = json.loads(f.read_text(encoding="utf-8"))
                self._items[inc["id"]] = inc
            except (OSError, ValueError, KeyError):
                continue
        self._loaded_from = d

    def _persist(self, inc: dict[str, Any]) -> None:
        path = self.directory / f"{inc['id']}.json"
        path.write_text(redact(json.dumps(inc, indent=2, default=str)), encoding="utf-8")

    # ------------------------------------------------------------------
    def create(self, alertname: str, alert: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.directory  # ensure loaded
            now = _now()
            inc = {
                "id": f"INC-{now:%Y%m%d-%H%M%S}-{_slug(alertname)}-{uuid.uuid4().hex[:4]}",
                "alertname": alertname,
                "status": "investigating",
                "severity": alert.get("labels", {}).get("severity", "unknown"),
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "alert": alert,
                "duplicates": 0,
                "events": [],
                "diagnosis": None,
                "proposed_action": None,
                "resolved_at": None,
                "postmortem": None,
            }
            self._items[inc["id"]] = inc
            self.add_event(inc["id"], "alert_received",
                           summary=alert.get("annotations", {}).get("summary", alertname))
            return inc

    def get(self, incident_id: str) -> dict[str, Any] | None:
        self.directory
        return self._items.get(incident_id)

    def list(self) -> list[dict[str, Any]]:
        self.directory
        with self._lock:
            return sorted(self._items.values(), key=lambda i: i["created_at"], reverse=True)

    def find_recent(self, alertname: str, window_seconds: int | None = None) -> dict[str, Any] | None:
        """Newest incident for this alert name inside the dedupe window."""
        window = window_seconds if window_seconds is not None else get_settings().dedupe_window_seconds
        cutoff = _now() - timedelta(seconds=window)
        for inc in self.list():
            if inc["alertname"] == alertname and datetime.fromisoformat(inc["created_at"]) >= cutoff:
                return inc
        return None

    def find_unresolved(self, alertname: str) -> dict[str, Any] | None:
        for inc in self.list():
            if inc["alertname"] == alertname and not inc["resolved_at"]:
                return inc
        return None

    def add_event(self, incident_id: str, kind: str, **data: Any) -> None:
        with self._lock:
            inc = self._items[incident_id]
            inc["events"].append({"ts": _now().isoformat(), "kind": kind, **data})
            inc["updated_at"] = _now().isoformat()
            self._persist(inc)

    def update(self, incident_id: str, **fields: Any) -> None:
        with self._lock:
            inc = self._items[incident_id]
            inc.update(fields)
            inc["updated_at"] = _now().isoformat()
            self._persist(inc)


store = IncidentStore()

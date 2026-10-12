"""Append-only JSONL audit log with secret redaction."""
import json
import os
import threading
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings

_lock = threading.Lock()
_SECRET_MARKERS = ("PASSWORD", "API_KEY", "SECRET", "TOKEN", "PASSWD")
OUTPUT_LIMIT = 2000


def _secret_values() -> list[str]:
    vals = {
        v for k, v in os.environ.items()
        if any(m in k.upper() for m in _SECRET_MARKERS) and len(v) >= 6
    }
    return sorted(vals, key=len, reverse=True)


def redact(text: str) -> str:
    for secret in _secret_values():
        text = text.replace(secret, "[REDACTED]")
    return text


def _clip(value: Any) -> Any:
    s = json.dumps(value, default=str)
    if len(s) <= OUTPUT_LIMIT:
        return value
    return s[:OUTPUT_LIMIT] + f"...[truncated {len(s) - OUTPUT_LIMIT} chars]"


def path():
    return get_settings().audit_dir / "audit.jsonl"


def record(**fields: Any) -> dict[str, Any]:
    entry = {"ts": datetime.now(timezone.utc).isoformat(), **fields}
    if "output" in entry:
        entry["output"] = _clip(entry["output"])
    line = redact(json.dumps(entry, default=str))
    with _lock:
        p = path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    return json.loads(line)


def tail(n: int = 50) -> list[dict[str, Any]]:
    p = path()
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        lines = f.readlines()[-n:]
    return [json.loads(x) for x in lines]

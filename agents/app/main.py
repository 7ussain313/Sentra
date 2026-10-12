import json
import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict

from app import container_metrics
from app.auth import require_user

log = logging.getLogger("sentra")

app = FastAPI(title="Sentra Agent Service")

UI_DIR = Path(__file__).parent / "ui"
AUDIT_DIR = Path("/app/audit")

# Most recent webhook deliveries, newest last. The incident store (Phase 7)
# replaces this; for now it proves the alert path end to end.
RECEIVED: deque[dict[str, Any]] = deque(maxlen=100)


class AlertmanagerPayload(BaseModel):
    """Alertmanager webhook v4 payload. Extra fields are kept, not rejected."""

    model_config = ConfigDict(extra="allow")

    status: str
    receiver: str = ""
    alerts: list[dict[str, Any]] = []
    groupLabels: dict[str, str] = {}
    commonLabels: dict[str, str] = {}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/ui")
def ui(_user: str = Depends(require_user)) -> FileResponse:
    return FileResponse(UI_DIR / "index.html")


@app.post("/webhook/alertmanager")
def alertmanager_webhook(payload: AlertmanagerPayload, user: str = Depends(require_user)) -> dict:
    record = {
        "received_at": datetime.now(timezone.utc).isoformat(),
        "status": payload.status,
        "alertnames": sorted({a.get("labels", {}).get("alertname", "?") for a in payload.alerts}),
        "payload": payload.model_dump(),
    }
    RECEIVED.append(record)
    log.warning("alert %s: %s", payload.status, record["alertnames"])
    try:
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        with (AUDIT_DIR / "alerts.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        log.exception("could not persist alert")
    return {"accepted": len(payload.alerts)}


@app.get("/alerts")
def recent_alerts(_user: str = Depends(require_user)) -> list[dict]:
    return [
        {k: r[k] for k in ("received_at", "status", "alertnames")} for r in reversed(RECEIVED)
    ]


@app.get("/metrics", response_class=PlainTextResponse)
def metrics(_user: str = Depends(require_user)) -> str:
    return container_metrics.render()

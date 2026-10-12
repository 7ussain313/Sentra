import json
import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from app import approvals, audit, business_agent, container_metrics, sre_agent
from app.incidents import store as incident_store
from app.auth import require_user

log = logging.getLogger("sentra")

app = FastAPI(title="Sentra Agent Service")
sre_agent.install_approval_gate()

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
    incident_ids = sre_agent.handle_alertmanager(payload.model_dump())
    return {"accepted": len(payload.alerts), "incidents": incident_ids}


@app.get("/alerts")
def recent_alerts(_user: str = Depends(require_user)) -> list[dict]:
    return [
        {k: r[k] for k in ("received_at", "status", "alertnames")} for r in reversed(RECEIVED)
    ]


@app.get("/metrics", response_class=PlainTextResponse)
def metrics(_user: str = Depends(require_user)) -> str:
    return container_metrics.render()


# ---- Minimal API used by the SRE flow; the full web UI is built on these in Phase 8 ----
@app.get("/api/incidents")
def list_incidents(_user: str = Depends(require_user)) -> list[dict]:
    keys = ("id", "alertname", "status", "severity", "created_at", "updated_at", "resolved_at",
            "duplicates", "postmortem")
    return [{k: i[k] for k in keys} for i in incident_store.list()]


@app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: str, _user: str = Depends(require_user)) -> dict:
    inc = incident_store.get(incident_id)
    if inc is None:
        raise HTTPException(404, "unknown incident")
    return inc


@app.get("/api/incidents/{incident_id}/postmortem", response_class=PlainTextResponse)
def get_postmortem(incident_id: str, _user: str = Depends(require_user)) -> str:
    inc = incident_store.get(incident_id)
    if inc is None or not inc.get("postmortem"):
        raise HTTPException(404, "no postmortem yet")
    return (incident_store.directory / inc["postmortem"]).read_text(encoding="utf-8")


@app.get("/api/approvals")
def list_approvals(_user: str = Depends(require_user)) -> list[dict]:
    return [a.public() for a in approvals.store.all()]


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approve: bool


@app.post("/api/approvals/{approval_id}")
def decide_approval(approval_id: str, body: Decision, user: str = Depends(require_user)) -> dict:
    try:
        return approvals.store.decide(approval_id, body.approve, user).public()
    except KeyError:
        raise HTTPException(404, "unknown approval")
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.get("/api/audit")
def audit_log(limit: int = 100, _user: str = Depends(require_user)) -> list[dict]:
    return list(reversed(audit.tail(max(1, min(limit, 500)))))


class AskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(..., min_length=3, max_length=500)


@app.post("/api/ask")
def ask(body: AskBody, _user: str = Depends(require_user)) -> dict:
    """Business agent: read-only answers from Odoo."""
    return business_agent.ask(body.question)

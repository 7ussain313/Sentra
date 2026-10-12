"""Throwaway demo server for UI checks: real FastAPI app, scripted model, fake restart.

    docker compose run --rm --no-deps -p 8001:8000 -e PYTHONPATH=/app \
        -e INCIDENTS_DIR=/tmp/inc -e AUDIT_DIR=/tmp/aud agents python tests/ui_demo_server.py

It never touches the real Odoo: restart_service is replaced by a no-op.
"""
import dataclasses
import time

import uvicorn

from app import sre_agent
from app.llm import LLMReply, ToolCall
from app.tools import registry

registry.TOOLS["restart_service"] = dataclasses.replace(
    registry.TOOLS["restart_service"], fn=lambda p: {"service": p.service, "success": True, "state": "running (demo)"})
registry.TOOLS["check_container_status"] = dataclasses.replace(
    registry.TOOLS["check_container_status"],
    fn=lambda p: [{"service": "odoo", "state": "exited", "health": "none", "restarts": 0, "exit_code": 137}])


def text(t):
    return LLMReply(text=t, blocks=[{"type": "text", "text": t}])


def use(name, args=None, preface=""):
    cid = f"tu_{name}_{time.monotonic_ns()}"
    blocks = ([{"type": "text", "text": preface}] if preface else []) + [
        {"type": "tool_use", "id": cid, "name": name, "input": args or {}}]
    return LLMReply(text=preface, tool_calls=[ToolCall(cid, name, args or {})], blocks=blocks)


class Demo:
    def __init__(self):
        self.script = [
            use("check_container_status", preface="Checking container state."),
            use("restart_service", {"service": "odoo"}, preface="Odoo exited; restarting is the smallest safe fix."),
            use("check_container_status", preface="Verifying."),
            text("## Diagnosis\nOdoo container exited (exit 137).\n## Result\nRunning again."),
            text("## Summary\nDemo.\n## Root cause\nDemo.\n## Resolution\nRestarted.\n## Prevention\n- Demo\n"),
        ]

    def complete(self, system, messages, tools=None, max_tokens=2048):
        return self.script.pop(0) if self.script else text("(end)")


sre_agent.set_llm_factory(Demo)
from app.main import app  # noqa: E402  (after patches)

uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")

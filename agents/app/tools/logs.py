from pydantic import Field

from app.tools.base import ServiceName, StrictInput, Tool, ToolError, truncate_text
from app.tools.containers import _client, service_container

MAX_CHARS = 20_000


class ReadLogsInput(StrictInput):
    service: ServiceName
    lines: int = Field(100, ge=1, le=500)


def read_logs(p: ReadLogsInput) -> dict:
    client = _client()
    try:
        container = service_container(client, p.service)
        try:
            raw = container.logs(tail=p.lines, timestamps=True)
        except Exception as e:
            raise ToolError(f"Could not read logs: {e}") from e
        text = raw.decode("utf-8", errors="replace")
        return {"service": p.service, "lines": text.count("\n"),
                "text": truncate_text(text, MAX_CHARS, keep="tail")}
    finally:
        client.close()


TOOL = Tool(
    name="read_logs",
    description="Read the most recent log lines of the 'odoo' or 'db' container (max 500).",
    model=ReadLogsInput,
    fn=read_logs,
    kind="read",
)

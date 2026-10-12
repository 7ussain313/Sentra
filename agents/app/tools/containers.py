from datetime import datetime, timezone

import docker
from docker.errors import DockerException

from app.config import get_settings
from app.tools.base import StrictInput, Tool, ToolError


def _client():
    try:
        return docker.from_env()
    except DockerException as e:
        raise ToolError(f"Docker is not reachable: {e}") from e


def service_container(client, service: str):
    """Find the compose container for an (already allowlisted) service."""
    project = get_settings().compose_project
    found = client.containers.list(
        all=True,
        filters={"label": [f"com.docker.compose.project={project}",
                           f"com.docker.compose.service={service}"]},
    )
    if not found:
        raise ToolError(f"No container found for service '{service}'")
    return found[0]


def _uptime(state: dict) -> float:
    if not state.get("Running"):
        return 0.0
    try:
        started = datetime.fromisoformat(state["StartedAt"].split(".")[0] + "+00:00")
        return max((datetime.now(timezone.utc) - started).total_seconds(), 0.0)
    except (KeyError, ValueError):
        return 0.0


class CheckContainerStatusInput(StrictInput):
    pass


def check_container_status(_: CheckContainerStatusInput) -> list[dict]:
    client = _client()
    try:
        project = get_settings().compose_project
        rows = []
        for c in client.containers.list(
            all=True, filters={"label": f"com.docker.compose.project={project}"}
        ):
            st = c.attrs.get("State", {})
            rows.append({
                "name": c.name,
                "service": c.labels.get("com.docker.compose.service", ""),
                "state": st.get("Status", "unknown"),
                "health": st.get("Health", {}).get("Status", "none"),
                "restarts": c.attrs.get("RestartCount", 0),
                "uptime_seconds": round(_uptime(st)),
                "exit_code": st.get("ExitCode") if not st.get("Running") else None,
            })
        return sorted(rows, key=lambda r: r["name"])
    finally:
        client.close()


TOOL = Tool(
    name="check_container_status",
    description="List the Sentra containers with state, health, restart count and uptime.",
    model=CheckContainerStatusInput,
    fn=check_container_status,
    kind="read",
)

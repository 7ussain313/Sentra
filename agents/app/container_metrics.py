"""Per-container metrics for Prometheus, read from the Docker socket.

cAdvisor cannot resolve container names on every host (for example Docker
Desktop with the containerd image store), so this exporter is the source for
the container dashboard and the ContainerMemoryHigh alert.
"""
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

import docker

log = logging.getLogger("sentra.containers")

PROJECT = "sentra"


def _memory_bytes(stats: dict[str, Any]) -> int:
    mem = stats.get("memory_stats", {})
    usage = mem.get("usage", 0)
    s = mem.get("stats", {})
    # Same definition `docker stats` uses: usage minus reclaimable page cache.
    cache = s.get("inactive_file", s.get("total_inactive_file", s.get("cache", 0)))
    return max(usage - cache, 0)


def _uptime_seconds(started_at: str) -> float:
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00").split(".")[0] + "+00:00")
        return max((datetime.now(start.tzinfo) - start).total_seconds(), 0.0)
    except ValueError:
        return 0.0


def _collect_one(container) -> dict[str, Any]:
    attrs = container.attrs
    state = attrs.get("State", {})
    info = {
        "name": container.name,
        "running": 1 if state.get("Running") else 0,
        "restarts": attrs.get("RestartCount", 0),
        "health": state.get("Health", {}).get("Status", "none"),
        "uptime": _uptime_seconds(state.get("StartedAt", "")) if state.get("Running") else 0.0,
        "memory": 0,
        "cpu_seconds": 0.0,
    }
    if info["running"]:
        try:
            stats = container.stats(stream=False)
            info["memory"] = _memory_bytes(stats)
            info["cpu_seconds"] = stats["cpu_stats"]["cpu_usage"]["total_usage"] / 1e9
        except Exception:  # container may vanish mid-scrape
            log.warning("no stats for %s", container.name, exc_info=True)
    return info


def collect() -> list[dict[str, Any]]:
    client = docker.from_env()
    try:
        containers = client.containers.list(
            all=True, filters={"label": f"com.docker.compose.project={PROJECT}"}
        )
        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(_collect_one, containers))
    finally:
        client.close()


def render() -> str:
    rows = collect()
    lines: list[str] = []

    def metric(name: str, help_: str, typ: str, key: str, fmt: str = "{}") -> None:
        lines.append(f"# HELP {name} {help_}")
        lines.append(f"# TYPE {name} {typ}")
        for r in rows:
            lines.append(f'{name}{{name="{r["name"]}"}} {fmt.format(r[key])}')

    metric("sentra_container_up", "1 if the container is running", "gauge", "running")
    metric("sentra_container_restarts", "Docker restart count", "gauge", "restarts")
    metric("sentra_container_uptime_seconds", "Seconds since the container started", "gauge", "uptime")
    metric("sentra_container_memory_bytes", "Working-set memory in bytes", "gauge", "memory")
    metric(
        "sentra_container_cpu_seconds_total",
        "Cumulative CPU time in seconds",
        "counter",
        "cpu_seconds",
    )
    lines.append("# HELP sentra_container_health Health status (1 for the current status)")
    lines.append("# TYPE sentra_container_health gauge")
    for r in rows:
        lines.append(f'sentra_container_health{{name="{r["name"]}",status="{r["health"]}"}} 1')
    return "\n".join(lines) + "\n"

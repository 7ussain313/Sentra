import httpx
from pydantic import Field

from app.config import get_settings
from app.tools.base import StrictInput, Tool, ToolError

MAX_SERIES = 50


class QueryMetricsInput(StrictInput):
    promql: str = Field(..., min_length=1, max_length=1000)


def query_metrics(p: QueryMetricsInput) -> dict:
    url = get_settings().prometheus_url.rstrip("/") + "/api/v1/query"
    try:
        r = httpx.get(url, params={"query": p.promql}, timeout=10)
        body = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise ToolError(f"Prometheus is not reachable: {e}") from e
    if body.get("status") != "success":
        raise ToolError(f"Prometheus rejected the query: {body.get('error', r.text[:200])}")
    data = body["data"]
    result = data.get("result", [])
    series = [
        {"metric": s.get("metric", {}), "value": s.get("value", [None, None])[1]}
        if data["resultType"] == "vector" else s
        for s in result[:MAX_SERIES]
    ]
    return {
        "resultType": data["resultType"],
        "total_series": len(result),
        "truncated": len(result) > MAX_SERIES,
        "series": series,
    }


TOOL = Tool(
    name="query_metrics",
    description="Run an instant PromQL query against Prometheus (max 50 series returned).",
    model=QueryMetricsInput,
    fn=query_metrics,
    kind="read",
)

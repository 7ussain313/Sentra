import psycopg2
from pydantic import Field

from app.config import get_settings
from app.tools.base import ServiceName, StrictInput, Tool, ToolError
from app.tools.containers import _client, service_container


class RestartServiceInput(StrictInput):
    service: ServiceName


def restart_service(p: RestartServiceInput) -> dict:
    client = _client()
    try:
        container = service_container(client, p.service)
        try:
            container.restart(timeout=30)
            container.reload()
        except Exception as e:
            raise ToolError(f"Restart failed: {e}") from e
        st = container.attrs["State"]
        return {
            "service": p.service,
            "success": bool(st.get("Running")),
            "state": st.get("Status"),
            "health": st.get("Health", {}).get("Status", "none"),
        }
    finally:
        client.close()


def _signal_conn():
    cfg = get_settings()
    return psycopg2.connect(
        host=cfg.db_host,
        port=cfg.db_port,
        dbname=cfg.odoo_db_name,
        user="sentra_signal",
        password=cfg.agent_db_signal_password,
        connect_timeout=5,
        application_name="sentra-agent-signal",
    )


class ClearOdooCacheInput(StrictInput):
    pass


def clear_odoo_cache(_: ClearOdooCacheInput) -> dict:
    try:
        conn = _signal_conn()
    except psycopg2.Error as e:
        raise ToolError(f"Database is not reachable: {str(e).splitlines()[0]}") from e
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT public.sentra_clear_odoo_cache()")
        return {"success": True, "detail": "Odoo caches are invalidated on the next request."}
    except psycopg2.Error as e:
        raise ToolError(f"Cache invalidation failed: {str(e).splitlines()[0]}") from e
    finally:
        conn.close()


class KillQueryInput(StrictInput):
    pid: int = Field(..., ge=2, le=4_194_304)


def kill_long_running_query(p: KillQueryInput) -> dict:
    try:
        conn = _signal_conn()
    except psycopg2.Error as e:
        raise ToolError(f"Database is not reachable: {str(e).splitlines()[0]}") from e
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT public.sentra_terminate_backend(%s)", (p.pid,))
            ok = cur.fetchone()[0]
        return {"pid": p.pid, "success": bool(ok)}
    except psycopg2.Error as e:
        # The SQL helper raises with a clear reason (not a client backend of the Odoo DB, ...).
        reason = str(e).splitlines()[0].removeprefix("ERROR:").strip()
        raise ToolError(f"Refused: {reason}") from e
    finally:
        conn.close()


RESTART = Tool(
    "restart_service",
    "Restart the 'odoo' or 'db' container. REQUIRES APPROVAL.",
    RestartServiceInput,
    restart_service,
    "action",
)
CLEAR_CACHE = Tool(
    "clear_odoo_cache",
    "Invalidate Odoo's ORM/QWeb/routing caches. REQUIRES APPROVAL.",
    ClearOdooCacheInput,
    clear_odoo_cache,
    "action",
)
KILL_QUERY = Tool(
    "kill_long_running_query",
    "Terminate one PostgreSQL client backend of the Odoo database by pid. REQUIRES APPROVAL.",
    KillQueryInput,
    kill_long_running_query,
    "action",
)

from __future__ import annotations

import json
import os
from typing import Any


class DatabricksConfigError(RuntimeError):
    pass


class DatabricksQueryError(RuntimeError):
    pass


def _get_env(name: str, required: bool = True, default: str | None = None) -> str:
    value = (os.getenv(name) or default or "").strip()
    if required and not value:
        raise DatabricksConfigError(f"Missing required Databricks setting: {name}")
    return value


def _connect():
    try:
        from databricks import sql  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise DatabricksConfigError(
            "databricks-sql-connector is not installed. Add it to backend requirements before enabling the Databricks provider."
        ) from exc

    host = _get_env("DBX_HOST")
    http_path = _get_env("DBX_HTTP_PATH")
    token = _get_env("DBX_TOKEN")
    socket_timeout_raw = _get_env("DBX_SOCKET_TIMEOUT_SECONDS", required=False, default="20")
    retry_attempts_raw = _get_env("DBX_RETRY_ATTEMPTS", required=False, default="2")
    retry_duration_raw = _get_env("DBX_RETRY_DURATION_SECONDS", required=False, default="30")
    retry_delay_raw = _get_env("DBX_RETRY_DELAY_SECONDS", required=False, default="1")
    try:
        socket_timeout = float(socket_timeout_raw)
    except ValueError:
        socket_timeout = 20.0
    try:
        retry_attempts = int(retry_attempts_raw)
    except ValueError:
        retry_attempts = 2
    try:
        retry_duration = float(retry_duration_raw)
    except ValueError:
        retry_duration = 30.0
    try:
        retry_delay = float(retry_delay_raw)
    except ValueError:
        retry_delay = 1.0

    try:
        return sql.connect(
            server_hostname=host,
            http_path=http_path,
            access_token=token,
            _socket_timeout=socket_timeout,
            _retry_stop_after_attempts_count=retry_attempts,
            _retry_stop_after_attempts_duration=retry_duration,
            _retry_delay_min=retry_delay,
            _retry_delay_max=max(5.0, retry_delay),
            _retry_delay_default=retry_delay,
        )
    except Exception as exc:  # pragma: no cover
        raise DatabricksQueryError(f"Failed to connect to Databricks SQL: {exc}") from exc


def fetch_all(query: str, parameters: list[Any] | None = None) -> list[dict]:
    parameters = parameters or []
    with _connect() as connection:
        with connection.cursor() as cursor:
            try:
                cursor.execute(query, parameters=parameters)
                rows = cursor.fetchall()
                columns = [d[0] for d in (cursor.description or [])]
            except Exception as exc:  # pragma: no cover
                raise DatabricksQueryError(f"Databricks query failed: {exc}") from exc
    return [dict(zip(columns, row)) for row in rows]


def fetch_one(query: str, parameters: list[Any] | None = None) -> dict | None:
    rows = fetch_all(query, parameters=parameters)
    return rows[0] if rows else None


def parse_json_field(value):
    if value in (None, "", []):
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value

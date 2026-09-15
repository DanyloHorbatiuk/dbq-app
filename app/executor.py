"""Executes SQL against a readonly pool inside BEGIN READ ONLY with
SET LOCAL statement_timeout — SPEC.md §ФВ-02/§4.1/§НФВ-08.

Only ever called with the readonly pool: routers/execute.py is the one
place that decides which SQL text reaches this module, and it always
either comes from a trusted catalog YAML file or has already passed
security.validate_readonly_sql().
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import psycopg
from psycopg import sql as psql
from psycopg.postgres import types as pg_types
from psycopg_pool import AsyncConnectionPool

# Independent of DEFAULT_ROW_LIMIT (a per-request default): this is a
# hard ceiling so a client can't ask for row_limit=10_000_000 and force
# the API to buffer an unbounded response in memory.
MAX_ROW_LIMIT = 50_000


@dataclass
class ExecutionResult:
    columns: list[dict[str, str]]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    roundtrip_ms: float


@dataclass
class DbErrorInfo:
    sqlstate: str | None
    message: str
    position: int | None


class QueryExecutionError(RuntimeError):
    """Wraps a psycopg.Error with the structured fields SPEC.md §НФВ-08
    requires in the API response (sqlstate, message, position) instead
    of a bare 500 with a Python traceback."""

    def __init__(self, info: DbErrorInfo) -> None:
        super().__init__(info.message)
        self.info = info


async def execute_readonly(
    pool: AsyncConnectionPool,
    sql_text: str,
    parameters: dict[str, Any] | None,
    row_limit: int,
    statement_timeout_ms: int,
) -> ExecutionResult:
    row_limit = min(row_limit, MAX_ROW_LIMIT)
    started = time.perf_counter()

    try:
        async with pool.connection() as conn, conn.transaction():
            # SET TRANSACTION READ ONLY (not "BEGIN READ ONLY" verbatim):
            # conn.transaction() already issues the BEGIN and guarantees
            # a COMMIT/ROLLBACK on the way out even if execute() below
            # raises — reimplementing that by hand around a literal
            # "BEGIN READ ONLY" would just be a worse version of what
            # this context manager already does. SET TRANSACTION READ
            # ONLY applies the same restriction to the transaction that's
            # already open.
            await conn.execute("SET TRANSACTION READ ONLY")
            # SET's grammar does not accept a bind parameter ($1) here —
            # confirmed against a real server; PostgreSQL raises a syntax
            # error. statement_timeout_ms is server configuration, never
            # client input, but psycopg.sql.Literal is used anyway rather
            # than an f-string: it's the correct tool for a value that
            # must be embedded directly in SQL text, and using it is what
            # makes this line self-evidently safe on inspection instead
            # of "safe because we happen to trust this particular caller".
            await conn.execute(
                psql.SQL("SET LOCAL statement_timeout = {}").format(
                    psql.Literal(statement_timeout_ms)
                )
            )

            async with conn.cursor() as cur:
                # None (not {}) when there are no parameters: passing any
                # params argument makes psycopg scan the query for %-style
                # placeholders, which would require every literal '%' in
                # catalog SQL (e.g. a LIKE pattern, or a ROUND(...)||'%')
                # to be escaped as '%%'. Skipping that scan entirely for
                # parameterless queries — the common case — avoids
                # surprising every catalog author with that rule.
                await cur.execute(sql_text, parameters or None)
                columns = _columns_from_cursor(cur)
                rows = await cur.fetchmany(row_limit + 1)
    except psycopg.Error as exc:
        raise QueryExecutionError(extract_error_info(exc)) from exc

    truncated = len(rows) > row_limit
    if truncated:
        rows = rows[:row_limit]

    roundtrip_ms = (time.perf_counter() - started) * 1000
    return ExecutionResult(
        columns=columns,
        rows=[[_jsonable(v) for v in row.values()] for row in rows],
        row_count=len(rows),
        truncated=truncated,
        roundtrip_ms=roundtrip_ms,
    )


def _jsonable(value: Any) -> Any:
    """NUMERIC/DECIMAL columns come back from psycopg as Decimal, which
    Pydantic serializes as a JSON *string* (to avoid silent precision
    loss) — but SPEC.md §ФВ-02's own example response shows plain
    unquoted numbers (4892.19), and Chart.js on the frontend (Etap 11)
    needs real numbers to plot, not strings it would have to parse back.
    This is a reporting tool, not a ledger, so that tradeoff is fine:
    float's precision is enough for every chart and total this project
    computes."""
    if isinstance(value, Decimal):
        return float(value)
    return value


def _columns_from_cursor(cur: psycopg.AsyncCursor[Any]) -> list[dict[str, str]]:
    if cur.description is None:
        return []
    return [
        {"name": col.name, "type": _pg_type_name(col.type_code)}
        for col in cur.description
    ]


def _pg_type_name(oid: int) -> str:
    info = pg_types.get(oid)
    return info.name if info else f"oid:{oid}"


def extract_error_info(exc: psycopg.Error) -> DbErrorInfo:
    """Public: also used by app.explain, which needs the same
    sqlstate/message/position extraction for EXPLAIN's own psycopg
    errors."""
    diag = getattr(exc, "diag", None)
    sqlstate = getattr(diag, "sqlstate", None) or getattr(exc, "sqlstate", None)
    message = (getattr(diag, "message_primary", None) or str(exc)).strip()
    position_str = getattr(diag, "statement_position", None)
    position = int(position_str) if position_str else None
    return DbErrorInfo(sqlstate=sqlstate, message=message, position=position)

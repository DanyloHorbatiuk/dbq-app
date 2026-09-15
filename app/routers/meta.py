"""System/meta endpoints — SPEC.md §ФВ-11 and ROADMAP.md Etap 4/5:
GET /api/health, GET /api/meta/server-info, GET /api/meta/schema,
GET /api/meta/coverage.

One router with explicit paths (not a shared prefix) because /api/health
and /api/meta/* sit at different depths under the app-level "/api"
prefix set in main.py. /api/meta/coverage lives here rather than in
routers/catalog.py (Etap 5's own file, per ROADMAP.md) because every
other /api/meta/* endpoint already does — keeping the whole path prefix
in one router beats a stricter reading of which stage "owns" the file.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from psycopg import AsyncConnection

from app.catalog import compute_coverage, get_catalog
from app.db import Database

router = APIRouter()

_SERVER_INFO_QUERY = """
    SELECT
        current_setting('server_version') AS server_version,
        current_setting('shared_buffers') AS shared_buffers,
        current_setting('work_mem') AS work_mem,
        current_setting('maintenance_work_mem') AS maintenance_work_mem,
        current_setting('effective_cache_size') AS effective_cache_size,
        current_setting('random_page_cost') AS random_page_cost,
        current_setting('default_statistics_target') AS default_statistics_target,
        current_setting('max_connections') AS max_connections
"""

_TABLES_QUERY = """
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_type = 'BASE TABLE'
      AND table_schema NOT IN ('pg_catalog', 'information_schema')
    ORDER BY table_schema, table_name
"""

_COLUMNS_QUERY = """
    SELECT table_name, column_name, data_type, is_nullable, column_default
    FROM information_schema.columns
    WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
    ORDER BY table_name, ordinal_position
"""

_INDEXES_QUERY = """
    SELECT tablename AS table_name, indexname AS index_name, indexdef AS definition
    FROM pg_indexes
    WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
    ORDER BY tablename, indexname
"""

_CONSTRAINTS_QUERY = """
    SELECT
        rel.relname AS table_name,
        con.conname AS constraint_name,
        con.contype AS constraint_type,
        pg_get_constraintdef(con.oid) AS definition
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    JOIN pg_namespace nsp ON nsp.oid = con.connamespace
    WHERE nsp.nspname NOT IN ('pg_catalog', 'information_schema')
    ORDER BY rel.relname, con.conname
"""


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    """Liveness + DB-reachability check; Dockerfile's HEALTHCHECK polls this."""
    pools = request.app.state.pools
    try:
        async with pools.get("museum", "readonly").connection() as conn:
            await conn.execute("SELECT 1")
    except Exception as exc:  # pragma: no cover - only hit when postgres is down
        raise HTTPException(
            status_code=503, detail=f"database unreachable: {exc}"
        ) from None
    return {"status": "ok"}


@router.get("/meta/server-info")
async def server_info(request: Request) -> dict[str, Any]:
    """PostgreSQL version and the planner-relevant settings that make
    benchmark numbers interpretable later (SPEC.md §ФВ-05's environment
    block reuses this query)."""
    pools = request.app.state.pools
    async with pools.get("museum", "readonly").connection() as conn:
        cur = await conn.execute(_SERVER_INFO_QUERY)
        row = await cur.fetchone()
    return dict(row) if row else {}


@router.get("/meta/schema")
async def schema(
    request: Request,
    database: Database = Query(..., description="museum | dvdrental"),
) -> dict[str, Any]:
    """Tables, columns, indexes and constraints — powers the "Структура
    БД" tab (SPEC.md §ФВ-11)."""
    pools = request.app.state.pools
    async with pools.get(database, "readonly").connection() as conn:
        tables = await _fetch(conn, _TABLES_QUERY)
        columns = await _fetch(conn, _COLUMNS_QUERY)
        indexes = await _fetch(conn, _INDEXES_QUERY)
        constraints = await _fetch(conn, _CONSTRAINTS_QUERY)

    by_table: dict[str, dict[str, Any]] = {
        t["table_name"]: {
            "schema": t["table_schema"],
            "columns": [],
            "indexes": [],
            "constraints": [],
        }
        for t in tables
    }
    _group_into(by_table, columns, "columns")
    _group_into(by_table, indexes, "indexes")
    _group_into(by_table, constraints, "constraints")

    return {
        "database": database,
        "tables": [{"name": name, **info} for name, info in sorted(by_table.items())],
    }


@router.get("/meta/coverage")
async def coverage() -> dict[str, Any]:
    """Which SQL capabilities from the control list (SPEC.md §3.2) the
    current catalog covers, and how many queries cover each — CLAUDE.md
    says to check this before adding a new catalog query, so it needs to
    reflect the catalog exactly as loaded, not a cached snapshot."""
    return compute_coverage(get_catalog())


async def _fetch(conn: AsyncConnection, query: str) -> list[dict[str, Any]]:
    cur = await conn.execute(query)
    return await cur.fetchall()


def _group_into(
    by_table: dict[str, dict[str, Any]], rows: list[dict[str, Any]], bucket: str
) -> None:
    """Splits each row's table_name off into by_table[name][bucket],
    dropping rows for tables outside the requested database's schema
    (introspection queries above deliberately don't filter by schema
    name, since museum's schema is "museum_network" but dvdrental's is
    "public" — filtering here instead of duplicating that mapping)."""
    for row in rows:
        key = row.pop("table_name")
        if key in by_table:
            by_table[key][bucket].append(row)

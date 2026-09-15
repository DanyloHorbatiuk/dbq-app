"""POST /api/execute — SPEC.md §ФВ-02 (catalog queries and variants)
and §ФВ-03 (arbitrary user SQL). Both paths share the same executor and
the same READ ONLY / saw_readonly guarantees; the only difference is
that arbitrary SQL is validated first (app.security) while catalog SQL
is trusted, authored content — the same way pgAdmin trusts whatever you
paste into it.
"""

from fastapi import APIRouter, HTTPException, Request

from app.catalog import get_catalog
from app.config import get_settings
from app.executor import QueryExecutionError, execute_readonly
from app.models import ColumnInfo, ExecuteRequest, ExecuteResponse, ExecuteTimings
from app.security import SqlValidationError, validate_readonly_sql

router = APIRouter()


@router.post("/execute")
async def execute(req: ExecuteRequest, request: Request) -> ExecuteResponse:
    settings = get_settings()
    row_limit = req.row_limit or settings.default_row_limit

    if req.query_id is not None:
        sql_text, database = _resolve_catalog_sql(req.query_id, req.variant)
    else:
        # ExecuteRequest._check_source guarantees sql/database are set
        # together with query_id unset, so these are never None here.
        assert req.sql is not None
        assert req.database is not None
        try:
            sql_text = validate_readonly_sql(req.sql)
        except SqlValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        database = req.database

    pool = request.app.state.pools.get(database, "readonly")

    try:
        result = await execute_readonly(
            pool, sql_text, req.parameters, row_limit, settings.statement_timeout_ms
        )
    except QueryExecutionError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "sqlstate": exc.info.sqlstate,
                "message": exc.info.message,
                "position": exc.info.position,
            },
        ) from None

    return ExecuteResponse(
        query_id=req.query_id,
        columns=[ColumnInfo(**c) for c in result.columns],
        rows=result.rows,
        row_count=result.row_count,
        truncated=result.truncated,
        timings=ExecuteTimings(roundtrip_ms=result.roundtrip_ms),
    )


def _resolve_catalog_sql(query_id: str, variant: int | None) -> tuple[str, str]:
    catalog = get_catalog()
    entry = catalog.get(query_id)
    if entry is None:
        raise HTTPException(
            status_code=404, detail=f"Unknown catalog query id: {query_id}"
        )

    if variant is None:
        return entry.sql, entry.database

    if not (0 <= variant < len(entry.variants)):
        raise HTTPException(
            status_code=400,
            detail=f"Query {query_id} has no variant {variant} (has {len(entry.variants)}).",
        )
    return entry.variants[variant].sql, entry.database

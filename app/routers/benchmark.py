"""POST /api/benchmark — SPEC.md §ФВ-05. Resolves query_id/variant or
raw sql + database the same way routers/execute.py and
routers/explain.py do (a benchmark is just N validated executions of
the same statement), then delegates the actual measurement to
app.benchmark, whose methodology is fixed per CLAUDE.md.
"""

from fastapi import APIRouter, HTTPException, Request

from app.benchmark import append_benchmark_csv, fetch_environment, run_benchmark
from app.catalog import get_catalog, resolve_variant_sql
from app.config import get_settings
from app.executor import QueryExecutionError
from app.models import (
    BenchmarkRequest,
    BenchmarkResponse,
    BenchmarkStatsOut,
    EnvironmentInfo,
)
from app.security import SqlValidationError, validate_readonly_sql

router = APIRouter()


@router.post("/benchmark")
async def benchmark(req: BenchmarkRequest, request: Request) -> BenchmarkResponse:
    settings = get_settings()
    row_limit = req.row_limit or settings.default_row_limit
    runs = req.runs or settings.benchmark_default_runs
    level: int | None = None

    if req.query_id is not None:
        catalog = get_catalog()
        entry = catalog.get(req.query_id)
        if entry is None:
            raise HTTPException(
                status_code=404, detail=f"Unknown catalog query id: {req.query_id}"
            )
        try:
            sql_text = resolve_variant_sql(entry, req.variant)
        except IndexError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        database = entry.database
        level = entry.level
    else:
        assert req.sql is not None
        assert req.database is not None
        try:
            sql_text = validate_readonly_sql(req.sql)
        except SqlValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        database = req.database

    pool = request.app.state.pools.get(database, "readonly")

    try:
        result = await run_benchmark(
            pool,
            sql_text,
            req.parameters,
            row_limit,
            settings.statement_timeout_ms,
            runs,
            req.discard_first,
        )
        environment = await fetch_environment(pool)
    except QueryExecutionError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "sqlstate": exc.info.sqlstate,
                "message": exc.info.message,
                "position": exc.info.position,
            },
        ) from None

    append_benchmark_csv(
        req.query_id, database, level, req.discard_first, result, environment
    )

    return BenchmarkResponse(
        query_id=req.query_id,
        runs=result.runs,
        cold_run_ms=result.cold_run_ms,
        stats=BenchmarkStatsOut(**vars(result.stats)),
        samples_ms=result.samples_ms,
        environment=EnvironmentInfo(**vars(environment)),
    )

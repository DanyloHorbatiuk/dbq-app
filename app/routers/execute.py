"""POST /api/execute — SPEC.md §ФВ-02 (catalog queries and variants)
and §ФВ-03 (arbitrary user SQL). Both paths share the same executor and
the same READ ONLY / saw_readonly guarantees; the only difference is
that arbitrary SQL is validated first (app.security) while catalog SQL
is trusted, authored content — the same way pgAdmin trusts whatever you
paste into it.
"""

from fastapi import APIRouter, HTTPException, Request

from app.catalog import get_catalog, resolve_variant_sql
from app.config import get_settings
from app.executor import QueryExecutionError, execute_readonly
from app.explain import explain_query
from app.models import (
    ColumnInfo,
    ExecuteRequest,
    ExecuteResponse,
    ExecuteTimings,
    PlanNodeOut,
    PlanSummary,
)
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

    timings = ExecuteTimings(roundtrip_ms=result.roundtrip_ms)
    plan_summary = None
    plan = None

    if req.with_plan:
        # A second round trip, deliberately: EXPLAIN never returns the
        # query's actual result rows (only the plan), so getting both
        # the table data above and a real EXPLAIN ANALYZE means running
        # the statement twice — there's no way around that with a single
        # Postgres query. Both runs share the same READ ONLY guarantees.
        try:
            explain_result = await explain_query(
                pool,
                sql_text,
                req.parameters,
                settings.statement_timeout_ms,
                analyze=True,
                buffers=True,
            )
        except QueryExecutionError:
            # The data query above already succeeded with this exact SQL
            # and these exact parameters, so a plan-only failure here
            # would be surprising rather than informative — degrade to
            # "no plan" instead of turning a successful execution into an
            # error response.
            pass
        else:
            timings.planning_ms = explain_result.planning_ms
            timings.execution_ms = explain_result.execution_ms
            plan = explain_result.plan
            plan_summary = PlanSummary(
                node_types=explain_result.node_types,
                slowest_node=_node_out(explain_result.slowest_node),
                estimation_error=explain_result.estimation_error,
            )

    return ExecuteResponse(
        query_id=req.query_id,
        columns=[ColumnInfo(**c) for c in result.columns],
        rows=result.rows,
        row_count=result.row_count,
        truncated=result.truncated,
        timings=timings,
        plan=plan,
        plan_summary=plan_summary,
    )


def _resolve_catalog_sql(query_id: str, variant: int | None) -> tuple[str, str]:
    catalog = get_catalog()
    entry = catalog.get(query_id)
    if entry is None:
        raise HTTPException(
            status_code=404, detail=f"Unknown catalog query id: {query_id}"
        )
    try:
        sql_text = resolve_variant_sql(entry, variant)
    except IndexError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return sql_text, entry.database


def _node_out(node: object) -> PlanNodeOut | None:
    if node is None:
        return None
    return PlanNodeOut(**node.__dict__)

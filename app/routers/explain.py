"""POST /api/explain — SPEC.md §ФВ-04. Mirrors routers/execute.py's
query_id/variant resolution and arbitrary-SQL validation exactly, since
"explain a query" and "run a query" share the same trust boundary
(EXPLAIN ANALYZE executes the statement it wraps).
"""

from fastapi import APIRouter, HTTPException, Request

from app.catalog import get_catalog, resolve_variant_sql
from app.config import get_settings
from app.executor import QueryExecutionError
from app.explain import explain_query
from app.models import ExplainRequest, ExplainResponse, PlanNodeOut, PlanSummary
from app.security import SqlValidationError, validate_readonly_sql

router = APIRouter()


@router.post("/explain")
async def explain(req: ExplainRequest, request: Request) -> ExplainResponse:
    settings = get_settings()

    if req.query_id is not None:
        sql_text, database = _resolve_catalog_sql(req.query_id, req.variant)
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
        result = await explain_query(
            pool,
            sql_text,
            req.parameters,
            settings.statement_timeout_ms,
            analyze=req.analyze,
            buffers=req.buffers,
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

    return ExplainResponse(
        query_id=req.query_id,
        plan=result.plan,
        nodes=[PlanNodeOut(**node.__dict__) for node in result.nodes],
        planning_ms=result.planning_ms,
        execution_ms=result.execution_ms,
        plan_summary=PlanSummary(
            node_types=result.node_types,
            slowest_node=PlanNodeOut(**result.slowest_node.__dict__)
            if result.slowest_node
            else None,
            estimation_error=result.estimation_error,
        ),
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

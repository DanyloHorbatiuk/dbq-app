"""GET /api/experiments, POST /api/experiments/{id}/run — SPEC.md
§ФВ-06/§ФВ-07. The client sends only experiment_id (path) and
keep_index (body) — never SQL or an index name, per CLAUDE.md's
security rule for the admin pool.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.catalog import get_catalog
from app.config import get_settings
from app.executor import QueryExecutionError
from app.experiment_runner import (
    IndexExperimentResult,
    ViewVsMatviewResult,
    append_index_experiment_csv,
    run_index_experiment,
    run_view_vs_matview_experiment,
)
from app.experiments import Experiment, IndexExperiment, get_experiments

router = APIRouter(prefix="/experiments", tags=["experiments"])


class ExperimentSummary(BaseModel):
    id: str
    kind: str
    database: str
    title: str
    description: str | None = None


class ExperimentRunRequest(BaseModel):
    keep_index: bool = False


@router.get("")
async def list_experiments() -> list[ExperimentSummary]:
    return [
        ExperimentSummary(
            id=e.id,
            kind=e.kind,
            database=e.database,
            title=e.title,
            description=e.description,
        )
        for e in sorted(get_experiments().values(), key=lambda e: e.id)
    ]


@router.post("/{experiment_id}/run")
async def run_experiment(
    experiment_id: str, req: ExperimentRunRequest, request: Request
) -> IndexExperimentResult | ViewVsMatviewResult:
    experiment = _get_experiment(experiment_id)
    settings = get_settings()
    pools = request.app.state.pools
    admin_pool = pools.get(experiment.database, "admin")
    readonly_pool = pools.get(experiment.database, "readonly")

    try:
        if isinstance(experiment, IndexExperiment):
            catalog = get_catalog()
            query = catalog.get(experiment.query_id)
            if query is None:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"Experiment {experiment_id} references unknown catalog "
                        f"query_id {experiment.query_id!r}"
                    ),
                )
            result: (
                IndexExperimentResult | ViewVsMatviewResult
            ) = await run_index_experiment(
                admin_pool,
                readonly_pool,
                experiment,
                query.sql,
                settings.default_row_limit,
                settings.statement_timeout_ms,
                settings.benchmark_default_runs,
                req.keep_index,
            )
            append_index_experiment_csv(result, experiment.database)
        else:
            result = await run_view_vs_matview_experiment(
                admin_pool,
                readonly_pool,
                experiment,
                settings.default_row_limit,
                settings.statement_timeout_ms,
                settings.benchmark_default_runs,
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

    return result


def _get_experiment(experiment_id: str) -> Experiment:
    experiment = get_experiments().get(experiment_id)
    if experiment is None:
        raise HTTPException(
            status_code=404, detail=f"Unknown experiment id: {experiment_id}"
        )
    return experiment

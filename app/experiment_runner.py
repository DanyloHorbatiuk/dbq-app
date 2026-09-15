"""Runs the experiments app.experiments loads — split out from that
module once it grew past CLAUDE.md's ~250-line guideline, the same way
executor.py/benchmark.py/explain.py are each a separate execution engine
from app.catalog's loading role.

Security (CLAUDE.md, non-negotiable): this is the *only* module in the
app that touches the admin connection pool, and it only ever runs SQL
that originates in an experiments/*.yaml file — create_sql, refresh_sql,
and the DROP INDEX/ANALYZE composed here from an experiment's own
already-validated index_name/table_name. The client sends only an
experiment_id and keep_index; it can never supply SQL or an identifier
that reaches the admin pool.
"""

from __future__ import annotations

import csv
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql as psql
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel

from app.benchmark import BenchmarkResult, run_benchmark
from app.executor import QueryExecutionError, extract_error_info
from app.experiments import IndexExperiment, ViewVsMatviewExperiment
from app.explain import ExplainResult, explain_query

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
INDEX_EXPERIMENTS_CSV = REPORTS_DIR / "index_experiments.csv"
PLANS_DIR = REPORTS_DIR / "plans"

_CSV_FIELDS = [
    "timestamp",
    "experiment_id",
    "title",
    "database",
    "index_name",
    "index_size",
    "create_index_ms",
    "kept_index",
    "before_median_ms",
    "after_median_ms",
    "before_scan_type",
    "after_scan_type",
]


class BenchmarkSnapshot(BaseModel):
    """One before/after side of an index experiment: the benchmark
    numbers plus the plan they came from."""

    stats: dict[str, float]
    scan_node_type: str | None
    plan: Any


class IndexExperimentResult(BaseModel):
    experiment_id: str
    title: str
    index_name: str
    index_size: str
    create_index_ms: float
    kept_index: bool
    before: BenchmarkSnapshot
    after: BenchmarkSnapshot


class ViewVsMatviewResult(BaseModel):
    experiment_id: str
    title: str
    refresh_ms: float
    matview_size: str
    view: BenchmarkSnapshot
    matview: BenchmarkSnapshot


def _ident(qualified: str) -> psql.Composed:
    """Turns a "schema.name" string from a trusted experiment YAML file
    into a safely quoted multi-part SQL identifier — CLAUDE.md: dynamic
    object names go through psycopg.sql.Identifier, never string
    formatting, even when (as here) the source is trusted YAML rather
    than client input."""
    return psql.Identifier(*qualified.split(".", 1))


async def _admin_execute(
    pool: AsyncConnectionPool, sql_text: psql.Composable | str, timeout_ms: int
) -> None:
    """Runs one trusted DDL/admin statement against the admin pool."""
    try:
        async with pool.connection() as conn, conn.transaction():
            await conn.execute(
                psql.SQL("SET LOCAL statement_timeout = {}").format(
                    psql.Literal(timeout_ms)
                )
            )
            await conn.execute(sql_text)
    except psycopg.Error as exc:
        raise QueryExecutionError(extract_error_info(exc)) from exc


async def _admin_execute_no_transaction(
    pool: AsyncConnectionPool, sql_text: str, timeout_ms: int
) -> None:
    """Same contract as _admin_execute, but without wrapping in an
    explicit transaction block: REFRESH MATERIALIZED VIEW CONCURRENTLY
    manages its own internal transactions and PostgreSQL rejects running
    it inside one of ours (confirmed against a real server while
    building this). autocommit=True on the admin pool (app/db.py) means
    each bare execute() here is still its own atomic unit."""
    try:
        async with pool.connection() as conn:
            await conn.execute(
                psql.SQL("SET statement_timeout = {}").format(psql.Literal(timeout_ms))
            )
            await conn.execute(sql_text)
            await conn.execute(
                "SET statement_timeout = 0"
            )  # session is pooled — don't leak it
    except psycopg.Error as exc:
        raise QueryExecutionError(extract_error_info(exc)) from exc


async def _relation_size(pool: AsyncConnectionPool, qualified_name: str) -> str:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT pg_size_pretty(pg_total_relation_size(%s::regclass))",
            (qualified_name,),
        )
        row = await cur.fetchone()
        return row["pg_size_pretty"]


def _scan_node_type(explain_result: ExplainResult) -> str | None:
    """The first node whose type mentions "Scan" — for a single-table
    demo query, this is the node an index experiment actually changes
    (Seq Scan -> Index Scan/Bitmap Heap Scan/Index Only Scan); the plan's
    root is usually an Aggregate or Sort wrapping it, not the scan
    itself, so reporting the root's type wouldn't show the thing this
    experiment is actually about."""
    for node in explain_result.nodes:
        if "Scan" in node.node_type:
            return node.node_type
    return None


def _save_plan(experiment_id: str, suffix: str, plan: Any) -> None:
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    path = PLANS_DIR / f"{experiment_id}_{suffix}.json"
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")


async def _snapshot(
    readonly_pool: AsyncConnectionPool,
    sql_text: str,
    row_limit: int,
    statement_timeout_ms: int,
    benchmark_runs: int,
    experiment_id: str,
    suffix: str,
) -> tuple[BenchmarkResult, BenchmarkSnapshot]:
    bench = await run_benchmark(
        readonly_pool,
        sql_text,
        None,
        row_limit,
        statement_timeout_ms,
        benchmark_runs,
        True,
    )
    explained = await explain_query(
        readonly_pool, sql_text, None, statement_timeout_ms, analyze=True, buffers=True
    )
    _save_plan(experiment_id, suffix, explained.plan)
    snapshot = BenchmarkSnapshot(
        stats=vars(bench.stats),
        scan_node_type=_scan_node_type(explained),
        plan=explained.plan,
    )
    return bench, snapshot


async def run_index_experiment(
    admin_pool: AsyncConnectionPool,
    readonly_pool: AsyncConnectionPool,
    experiment: IndexExperiment,
    query_sql: str,
    row_limit: int,
    statement_timeout_ms: int,
    benchmark_runs: int,
    keep_index: bool,
) -> IndexExperimentResult:
    """The six-step scenario SPEC.md §ФВ-06 spells out, in order."""
    index_ident = _ident(experiment.index_name)
    table_ident = _ident(experiment.table_name)

    # 1. No index, fresh statistics.
    await _admin_execute(
        admin_pool,
        psql.SQL("DROP INDEX IF EXISTS {}").format(index_ident),
        statement_timeout_ms,
    )
    await _admin_execute(
        admin_pool, psql.SQL("ANALYZE {}").format(table_ident), statement_timeout_ms
    )

    # 2. Benchmark + plan without the index.
    _, before = await _snapshot(
        readonly_pool,
        query_sql,
        row_limit,
        statement_timeout_ms,
        benchmark_runs,
        experiment.id,
        "before",
    )

    # 3. Create the index (timed) + fresh statistics.
    started = time.perf_counter()
    await _admin_execute(admin_pool, experiment.create_sql, statement_timeout_ms)
    create_index_ms = (time.perf_counter() - started) * 1000
    await _admin_execute(
        admin_pool, psql.SQL("ANALYZE {}").format(table_ident), statement_timeout_ms
    )

    # 4. Benchmark + plan with the index.
    _, after = await _snapshot(
        readonly_pool,
        query_sql,
        row_limit,
        statement_timeout_ms,
        benchmark_runs,
        experiment.id,
        "after",
    )

    # 5. Index size (read via the readonly pool — this is a plain SELECT).
    index_size = await _relation_size(readonly_pool, experiment.index_name)

    # 6. Revert unless asked to keep it.
    if not keep_index:
        await _admin_execute(
            admin_pool,
            psql.SQL("DROP INDEX IF EXISTS {}").format(index_ident),
            statement_timeout_ms,
        )

    return IndexExperimentResult(
        experiment_id=experiment.id,
        title=experiment.title,
        index_name=experiment.index_name,
        index_size=index_size,
        create_index_ms=round(create_index_ms, 3),
        kept_index=keep_index,
        before=before,
        after=after,
    )


async def run_view_vs_matview_experiment(
    admin_pool: AsyncConnectionPool,
    readonly_pool: AsyncConnectionPool,
    experiment: ViewVsMatviewExperiment,
    row_limit: int,
    statement_timeout_ms: int,
    benchmark_runs: int,
) -> ViewVsMatviewResult:
    """SPEC.md §ФВ-07: benchmark the view, time a REFRESH, benchmark the
    freshly refreshed materialized view, report its size."""
    _, view_snapshot = await _snapshot(
        readonly_pool,
        experiment.sql_view,
        row_limit,
        statement_timeout_ms,
        benchmark_runs,
        experiment.id,
        "view",
    )

    started = time.perf_counter()
    await _admin_execute_no_transaction(
        admin_pool, experiment.refresh_sql, statement_timeout_ms
    )
    refresh_ms = (time.perf_counter() - started) * 1000

    _, matview_snapshot = await _snapshot(
        readonly_pool,
        experiment.sql_matview,
        row_limit,
        statement_timeout_ms,
        benchmark_runs,
        experiment.id,
        "matview",
    )
    matview_size = await _relation_size(readonly_pool, experiment.matview_name)

    return ViewVsMatviewResult(
        experiment_id=experiment.id,
        title=experiment.title,
        refresh_ms=round(refresh_ms, 3),
        matview_size=matview_size,
        view=view_snapshot,
        matview=matview_snapshot,
    )


def append_index_experiment_csv(result: IndexExperimentResult, database: str) -> None:
    """CLAUDE.md: "Не пиши в reports/ вручну" — this is the code that
    writes reports/index_experiments.csv, called once per index
    experiment run (not for view_vs_matview: §8 describes this file as
    specifically "результати експериментів з індексами")."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    is_new = not INDEX_EXPERIMENTS_CSV.exists()

    row = {
        "timestamp": datetime.now(UTC).isoformat(),
        "experiment_id": result.experiment_id,
        "title": result.title,
        "database": database,
        "index_name": result.index_name,
        "index_size": result.index_size,
        "create_index_ms": result.create_index_ms,
        "kept_index": result.kept_index,
        "before_median_ms": result.before.stats["median_ms"],
        "after_median_ms": result.after.stats["median_ms"],
        "before_scan_type": result.before.scan_node_type,
        "after_scan_type": result.after.scan_node_type,
    }

    with INDEX_EXPERIMENTS_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)

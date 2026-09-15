"""Benchmarking methodology — SPEC.md §ФВ-05.

Fixed once, per CLAUDE.md's own explicit warning not to "improve" this
mid-project: N runs (each one a full call through executor.execute_readonly(),
the same path POST /api/execute uses — a benchmark measures exactly what
a user experiences, not an idealized server-only timing), the first run
set aside as "cold" and excluded from the statistics, median as the
primary number, min/mean/p95/max/stddev alongside it, an environment
block on every result, and every result appended to reports/benchmarks.csv.
"""

from __future__ import annotations

import csv
import statistics
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from psycopg_pool import AsyncConnectionPool

from app.executor import execute_readonly

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
BENCHMARKS_CSV = REPORTS_DIR / "benchmarks.csv"

_CSV_FIELDS = [
    "timestamp",
    "query_id",
    "database",
    "level",
    "runs",
    "discard_first",
    "cold_run_ms",
    "min_ms",
    "median_ms",
    "mean_ms",
    "p95_ms",
    "max_ms",
    "stddev_ms",
    "server_version",
    "shared_buffers",
    "work_mem",
    "random_page_cost",
]


@dataclass
class BenchmarkStats:
    min_ms: float
    median_ms: float
    mean_ms: float
    p95_ms: float
    max_ms: float
    stddev_ms: float


@dataclass
class BenchmarkResult:
    runs: int
    cold_run_ms: float
    stats: BenchmarkStats
    samples_ms: list[float]


@dataclass
class Environment:
    server_version: str
    shared_buffers: str
    work_mem: str
    random_page_cost: str
    table_sizes: dict[str, str]


async def run_benchmark(
    pool: AsyncConnectionPool,
    sql_text: str,
    parameters: dict[str, Any] | None,
    row_limit: int,
    statement_timeout_ms: int,
    runs: int,
    discard_first: bool,
) -> BenchmarkResult:
    """Runs sql_text `runs` times, sequentially (never in parallel — a
    concurrent run would contend for the same buffers/CPU and stop each
    sample from measuring the query on its own). cold_cache, accepted by
    the request model for parity with SPEC.md's example payload, is
    deliberately not implemented as a real cache flush: doing that would
    need either restarting PostgreSQL or an OS-level `drop_caches`, both
    superuser/root operations with no place in a read-only API. The
    first run's timing is reported as cold_run_ms regardless — it is
    genuinely the coldest of the N runs, just not a guaranteed
    from-nothing cold start.
    """
    timings_ms: list[float] = []
    for _ in range(runs):
        result = await execute_readonly(
            pool, sql_text, parameters, row_limit, statement_timeout_ms
        )
        timings_ms.append(result.roundtrip_ms)

    cold_run_ms = timings_ms[0]
    samples = timings_ms[1:] if discard_first else timings_ms

    return BenchmarkResult(
        runs=runs,
        cold_run_ms=cold_run_ms,
        stats=_compute_stats(samples),
        samples_ms=samples,
    )


def _compute_stats(samples: list[float]) -> BenchmarkStats:
    sorted_samples = sorted(samples)
    return BenchmarkStats(
        min_ms=min(samples),
        median_ms=statistics.median(samples),
        mean_ms=statistics.mean(samples),
        p95_ms=_percentile(sorted_samples, 0.95),
        max_ms=max(samples),
        stddev_ms=statistics.stdev(samples) if len(samples) > 1 else 0.0,
    )


def _percentile(sorted_samples: list[float], p: float) -> float:
    """Linear-interpolation percentile between the two nearest ranks —
    the same method numpy's default uses, simple enough to not need
    numpy as a dependency just for this."""
    n = len(sorted_samples)
    if n == 1:
        return sorted_samples[0]
    rank = p * (n - 1)
    lo = int(rank)
    hi = min(lo + 1, n - 1)
    frac = rank - lo
    return sorted_samples[lo] + (sorted_samples[hi] - sorted_samples[lo]) * frac


async def fetch_environment(pool: AsyncConnectionPool) -> Environment:
    """table_sizes covers every base table in the target database's own
    schema (museum_network or public — whichever the pool's connections
    land in, so no schema name needs passing in here), not just the
    tables the benchmarked query happens to touch: knowing exactly which
    tables a given SQL string references would need real SQL parsing,
    while every table in the schema is simple, always correct, and still
    gives the volume context a benchmark number needs to be
    interpretable.
    """
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT
                current_setting('server_version') AS server_version,
                current_setting('shared_buffers') AS shared_buffers,
                current_setting('work_mem') AS work_mem,
                current_setting('random_page_cost') AS random_page_cost
            """
        )
        settings_row = await cur.fetchone()

        cur = await conn.execute(
            """
            SELECT
                n.nspname || '.' || c.relname AS table_name,
                pg_size_pretty(pg_total_relation_size(c.oid)) AS size
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'r'
              AND n.nspname NOT IN ('pg_catalog', 'information_schema')
            ORDER BY pg_total_relation_size(c.oid) DESC
            """
        )
        size_rows = await cur.fetchall()

    return Environment(
        server_version=settings_row["server_version"],
        shared_buffers=settings_row["shared_buffers"],
        work_mem=settings_row["work_mem"],
        random_page_cost=settings_row["random_page_cost"],
        table_sizes={r["table_name"]: r["size"] for r in size_rows},
    )


def append_benchmark_csv(
    query_id: str | None,
    database: str,
    level: int | None,
    discard_first: bool,
    result: BenchmarkResult,
    environment: Environment,
) -> None:
    """CLAUDE.md: "Не пиши в reports/ вручну — ці файли генеруються
    кодом" — this is that code, called once per POST /api/benchmark so
    every measurement that was ever run through the API ends up in the
    report file, not just the ones someone remembered to export."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    is_new = not BENCHMARKS_CSV.exists()

    row = {
        "timestamp": datetime.now(UTC).isoformat(),
        "query_id": query_id or "ad-hoc",
        "database": database,
        "level": level if level is not None else "",
        "runs": result.runs,
        "discard_first": discard_first,
        "cold_run_ms": round(result.cold_run_ms, 3),
        **{k: round(v, 3) for k, v in asdict(result.stats).items()},
        "server_version": environment.server_version,
        "shared_buffers": environment.shared_buffers,
        "work_mem": environment.work_mem,
        "random_page_cost": environment.random_page_cost,
    }

    with BENCHMARKS_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)

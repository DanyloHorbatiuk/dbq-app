"""The individual SPEC.md §7 checks scripts/verify.py orchestrates —
split out on its own because verify.py plus every check in one file
passed CLAUDE.md's ~250-line-per-module guideline.
"""

from __future__ import annotations

import csv
import re
import subprocess
import sys
from pathlib import Path

from psycopg import sql as psql
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.executor import QueryExecutionError, execute_readonly
from app.experiment_runner import append_index_experiment_csv, run_index_experiment
from app.experiments import IndexExperiment, get_experiments
from scripts.verify_report import Report

ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT / "reports"

# SPEC.md §2.2.6.
MUSEUM_MIN_ROWS = {
    "halls": 20,
    "artifact_types": 40,
    "exhibits": 5_000,
    "staff": 200,
    "exhibitions": 400,
    "exhibition_items": 30_000,
    "ticket_prices": 4_000,
    "tickets": 300_000,
    "visitor_feedback": 80_000,
    "guided_tours": 8_000,
    "tour_bookings": 50_000,
    "restorations": 3_000,
}

MIN_INDEX_EXPERIMENTS_WITH_SCAN_CHANGE = 5  # SPEC.md §7.6
MIN_TESTS = 25  # SPEC.md §НФВ-07


def pool_for(settings, database: str, role: str) -> AsyncConnectionPool:
    db_name = settings.museum_db if database == "museum" else settings.dvdrental_db
    return AsyncConnectionPool(
        conninfo=settings.conninfo(db_name, role),
        min_size=1,
        max_size=5,
        kwargs={"row_factory": dict_row, "autocommit": True},
        open=False,
    )


async def check_db_reachable(
    pools: dict[str, AsyncConnectionPool], report: Report
) -> bool:
    ok = True
    for database, pool in pools.items():
        try:
            async with pool.connection() as conn:
                await conn.execute("SELECT 1")
        except Exception as exc:  # noqa: BLE001 - reporting, not handling
            report.check(f"Розгортання: БД {database} доступна", False, str(exc))
            ok = False
        else:
            report.check(f"Розгортання: БД {database} доступна", True)
    return ok


def print_catalog_counts(catalog, report: Report) -> None:
    by_db_level: dict[tuple[str, int], int] = {}
    for entry in catalog.values():
        key = (entry.database, entry.level)
        by_db_level[key] = by_db_level.get(key, 0) + 1
    for database in ("museum", "dvdrental"):
        counts = [by_db_level.get((database, lvl), 0) for lvl in (1, 2, 3, 4)]
        report.info(
            f"  {database}: рівень1={counts[0]} рівень2={counts[1]} "
            f"рівень3={counts[2]} рівень4={counts[3]} усього={sum(counts)}"
        )


def write_coverage_csv(coverage: dict) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with (REPORTS_DIR / "catalog_coverage.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.writer(f)
        writer.writerow(["level", "feature", "covered", "query_count"])
        for level, data in coverage["by_level"].items():
            for feature in sorted(set(data["counts"]) | set(data["missing"])):
                writer.writerow(
                    [
                        level,
                        feature,
                        feature in data["counts"],
                        data["counts"].get(feature, 0),
                    ]
                )


async def fetch_table_sizes(pools: dict[str, AsyncConnectionPool]) -> dict[str, str]:
    # SPEC.md §8: table_sizes.csv covers "обидві бази" — every pool passed
    # in gets queried, schema-qualified names (museum_network.* vs public.*)
    # keep the two databases' tables from colliding in one flat dict.
    sizes: dict[str, str] = {}
    for pool in pools.values():
        async with pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT n.nspname || '.' || c.relname AS table_name,
                       pg_size_pretty(pg_total_relation_size(c.oid)) AS size
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind = 'r' AND n.nspname NOT IN ('pg_catalog', 'information_schema')
                ORDER BY pg_total_relation_size(c.oid) DESC
                """
            )
            rows = await cur.fetchall()
        sizes.update({r["table_name"]: r["size"] for r in rows})
    return sizes


def write_table_sizes_csv(table_sizes: dict[str, str]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with (REPORTS_DIR / "table_sizes.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["table", "size"])
        for table, size in table_sizes.items():
            writer.writerow([table, size])


def run_test_suite() -> tuple[int, bool]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"], cwd=ROOT, capture_output=True, text=True
    )
    print(result.stdout)
    if result.returncode not in (0, 1):
        print(result.stderr, file=sys.stderr)
    summary = next(
        (line for line in reversed(result.stdout.splitlines()) if line.strip()), ""
    )
    passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", summary)) else 0
    failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", summary)) else 0
    errors = int(m.group(1)) if (m := re.search(r"(\d+) error", summary)) else 0
    return passed + failed + errors, result.returncode == 0


async def check_museum_volumes(pool: AsyncConnectionPool, report: Report) -> None:
    async with pool.connection() as conn:
        for table, minimum in MUSEUM_MIN_ROWS.items():
            cur = await conn.execute(
                psql.SQL("SELECT COUNT(*) AS n FROM museum_network.{}").format(
                    psql.Identifier(table)
                )
            )
            row = await cur.fetchone()
            report.check(
                f"{table}: {row['n']} (мінімум {minimum})", row["n"] >= minimum
            )


async def check_catalog_runs(
    catalog, pools: dict[str, AsyncConnectionPool], report: Report
) -> None:
    failures: list[str] = []
    for entry in catalog.values():
        pool = pools[entry.database]
        cases = [(None, entry.sql)] + [(i, v.sql) for i, v in enumerate(entry.variants)]
        for label, sql_text in cases:
            try:
                await execute_readonly(pool, sql_text, None, 10, 15000)
            except QueryExecutionError as exc:
                who = entry.id if label is None else f"{entry.id} (variant {label})"
                failures.append(f"{who}: {exc.info.message}")
    report.check(
        f"{len(catalog)} запитів + варіанти виконано без помилок",
        not failures,
        "усі успішно"
        if not failures
        else f"{len(failures)} провалів, напр.: {failures[0]}",
    )


async def check_index_experiments(
    catalog,
    admin_pool: AsyncConnectionPool,
    readonly_pool: AsyncConnectionPool,
    settings,
    report: Report,
) -> None:
    experiments = [
        e for e in get_experiments().values() if isinstance(e, IndexExperiment)
    ]
    changed = 0
    for experiment in experiments:
        query = catalog.get(experiment.query_id)
        if query is None:
            report.info(
                f"  {experiment.id}: query_id '{experiment.query_id}' не знайдено в каталозі"
            )
            continue
        try:
            result = await run_index_experiment(
                admin_pool,
                readonly_pool,
                experiment,
                query.sql,
                settings.default_row_limit,
                settings.statement_timeout_ms,
                settings.benchmark_default_runs,
                keep_index=False,
            )
        except QueryExecutionError as exc:
            report.info(f"  {experiment.id}: помилка — {exc.info.message}")
            continue
        append_index_experiment_csv(result, experiment.database)
        report.info(
            f"  {experiment.id}: {result.before.scan_node_type} -> {result.after.scan_node_type}, "
            f"медіана {result.before.stats['median_ms']:.2f} -> {result.after.stats['median_ms']:.2f} мс"
        )
        if result.before.scan_node_type != result.after.scan_node_type:
            changed += 1
    report.check(
        f"Експериментів зі зміною вузла доступу: {changed} "
        f"(мінімум {MIN_INDEX_EXPERIMENTS_WITH_SCAN_CHANGE})",
        changed >= MIN_INDEX_EXPERIMENTS_WITH_SCAN_CHANGE,
    )


def check_benchmarks_csv(report: Report) -> None:
    path = REPORTS_DIR / "benchmarks.csv"
    if not path.exists():
        report.check(
            "reports/benchmarks.csv існує", False, "запустіть 'make bench' спочатку"
        )
        return
    with path.open(encoding="utf-8") as f:
        rows = list(csv.reader(f))
    data_rows = max(0, len(rows) - 1)
    report.check(
        f"reports/benchmarks.csv містить вимірювання: {data_rows}", data_rows > 0
    )

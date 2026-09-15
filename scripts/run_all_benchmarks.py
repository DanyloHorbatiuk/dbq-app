"""make bench — benchmarks every catalog query, and every plan-comparison
variant, once each with the project's fixed methodology
(app.benchmark.run_benchmark: N runs, cold run set aside, median as the
headline number — CLAUDE.md: never "improve" this mid-project). Each
result is appended to reports/benchmarks.csv via the same
append_benchmark_csv() the API itself calls on every POST /api/benchmark,
so this script and the live API always produce rows in the same format.

Only opens a pool for a database the catalog actually references, so
this runs cleanly today with dvdrental's catalog still empty (see
TODO.md) and will pick up dvdrental queries automatically once they
exist — no changes needed here.
"""

from __future__ import annotations

import asyncio

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.benchmark import append_benchmark_csv, fetch_environment, run_benchmark
from app.catalog import DEFAULT_CATALOG_ROOT, load_catalog
from app.config import get_settings


async def main() -> None:
    settings = get_settings()
    catalog = load_catalog(DEFAULT_CATALOG_ROOT)
    pools = await _open_pools(settings, catalog)

    total = 0
    for entry in sorted(catalog.values(), key=lambda e: e.id):
        pool = pools[entry.database]
        cases = [(entry.id, entry.sql)] + [
            (f"{entry.id}#variant{i}", v.sql) for i, v in enumerate(entry.variants)
        ]
        for label, sql_text in cases:
            total += 1
            print(f"[{total}] {label} ...", end=" ", flush=True)
            result = await run_benchmark(
                pool,
                sql_text,
                None,
                settings.default_row_limit,
                settings.statement_timeout_ms,
                settings.benchmark_default_runs,
                True,
            )
            environment = await fetch_environment(pool)
            append_benchmark_csv(
                label, entry.database, entry.level, True, result, environment
            )
            print(f"медіана {result.stats.median_ms:.2f} мс")

    for pool in pools.values():
        await pool.close()

    print(f"\nГотово: {total} вимірювань записано у reports/benchmarks.csv")


async def _open_pools(settings, catalog) -> dict[str, AsyncConnectionPool]:
    pools: dict[str, AsyncConnectionPool] = {}
    for database in sorted({entry.database for entry in catalog.values()}):
        db_name = settings.museum_db if database == "museum" else settings.dvdrental_db
        pool = AsyncConnectionPool(
            conninfo=settings.conninfo(db_name, "readonly"),
            min_size=1,
            max_size=5,
            kwargs={"row_factory": dict_row, "autocommit": True},
            open=False,
        )
        await pool.open()
        pools[database] = pool
    return pools


if __name__ == "__main__":
    asyncio.run(main())

"""Runs every catalog query — and every plan-comparison variant — against
the real database it targets, per ROADMAP.md's Etap 10 check and SPEC.md
§7.5: "кожен запит каталогу успішно виконується (перевіряється автотестом,
що прогонує весь каталог)".

Opens one pool per database the catalog actually references (not just
conftest.py's single museum readonly_pool), so this file picked up
dvdrental automatically once its catalog stopped being empty — no other
change was needed here beyond this fixture.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.catalog import DEFAULT_CATALOG_ROOT, load_catalog
from app.config import get_settings
from app.executor import execute_readonly

_CATALOG = load_catalog(DEFAULT_CATALOG_ROOT)
_MAIN_CASES = sorted((entry.database, entry.id) for entry in _CATALOG.values())
_VARIANT_CASES = sorted(
    (entry.database, entry.id, i)
    for entry in _CATALOG.values()
    for i in range(len(entry.variants))
)


@pytest_asyncio.fixture()
async def readonly_pools() -> AsyncIterator[dict[str, AsyncConnectionPool]]:
    settings = get_settings()
    db_names = {"museum": settings.museum_db, "dvdrental": settings.dvdrental_db}
    pools: dict[str, AsyncConnectionPool] = {}
    for database in {entry.database for entry in _CATALOG.values()}:
        pool = AsyncConnectionPool(
            conninfo=settings.conninfo(db_names[database], "readonly"),
            min_size=1,
            max_size=5,
            kwargs={"row_factory": dict_row, "autocommit": True},
            open=False,
        )
        await pool.open()
        pools[database] = pool
    yield pools
    for pool in pools.values():
        await pool.close()


@pytest.mark.parametrize("database,query_id", _MAIN_CASES)
async def test_catalog_query_executes(database, query_id, readonly_pools):
    entry = _CATALOG[query_id]
    result = await execute_readonly(
        readonly_pools[database], entry.sql, None, 50, 15000
    )
    assert result.row_count >= 0  # not raising is the actual assertion


@pytest.mark.parametrize("database,query_id,variant_index", _VARIANT_CASES)
async def test_catalog_variant_executes(
    database, query_id, variant_index, readonly_pools
):
    entry = _CATALOG[query_id]
    sql_text = entry.variants[variant_index].sql
    result = await execute_readonly(readonly_pools[database], sql_text, None, 50, 15000)
    assert result.row_count >= 0


def test_catalog_meets_spec_size_minimums():
    # SPEC.md §7.4: >=55 queries total, >=20 at level 3. Guards against
    # silently collecting fewer parametrize cases too (e.g. a catalog
    # path change) — the two tests above would then report a deceptive
    # "N passed" for a much smaller N instead of a real signal.
    assert len(_MAIN_CASES) >= 55
    assert sum(1 for entry in _CATALOG.values() if entry.level == 3) >= 20

"""Runs every catalog query — and every plan-comparison variant — against
the real database, per ROADMAP.md's Etap 10 check and SPEC.md §7.5:
"кожен запит каталогу успішно виконується (перевіряється автотестом, що
прогонує весь каталог)".

Every entry currently loaded targets museum (dvdrental's catalog is still
empty — see TODO.md), so this only needs the museum readonly pool; the
assertion below turns "someone adds a dvdrental query" into a loud
collection-time failure instead of a silently-skipped test, as a reminder
that this file will need a dvdrental pool fixture added alongside it.
"""

import pytest

from app.catalog import DEFAULT_CATALOG_ROOT, load_catalog
from app.executor import execute_readonly

_CATALOG = load_catalog(DEFAULT_CATALOG_ROOT)
assert all(entry.database == "museum" for entry in _CATALOG.values()), (
    "A non-museum catalog entry exists — test_catalog_runs.py needs a "
    "readonly_pool fixture for that database before it can execute it."
)

_MAIN_IDS = sorted(_CATALOG)
_VARIANT_CASES = sorted(
    (entry.id, i) for entry in _CATALOG.values() for i in range(len(entry.variants))
)


@pytest.mark.parametrize("query_id", _MAIN_IDS)
async def test_catalog_query_executes(query_id, readonly_pool):
    entry = _CATALOG[query_id]
    result = await execute_readonly(readonly_pool, entry.sql, None, 50, 15000)
    assert result.row_count >= 0  # not raising is the actual assertion


@pytest.mark.parametrize("query_id,variant_index", _VARIANT_CASES)
async def test_catalog_variant_executes(query_id, variant_index, readonly_pool):
    entry = _CATALOG[query_id]
    sql_text = entry.variants[variant_index].sql
    result = await execute_readonly(readonly_pool, sql_text, None, 50, 15000)
    assert result.row_count >= 0


def test_catalog_run_actually_covers_every_entry():
    # Guards against silently collecting zero parametrize cases (e.g. if
    # the catalog path ever changed) — the two tests above would then
    # report a deceptive "0 passed" instead of a real signal.
    assert len(_MAIN_IDS) >= 25

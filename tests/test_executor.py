"""Unit tests for app.executor's pure helpers, plus integration tests
against the real readonly pool: the READ ONLY execution path, row-limit
truncation, and structured error reporting (SPEC.md §НФВ-08 — sqlstate/
message/position, never a bare 500 with a traceback).
"""

from decimal import Decimal

import pytest

from app.executor import MAX_ROW_LIMIT, QueryExecutionError, _jsonable, execute_readonly


def test_jsonable_converts_decimal_to_float():
    assert _jsonable(Decimal("42.50")) == 42.5
    assert isinstance(_jsonable(Decimal("1")), float)


def test_jsonable_passes_through_non_decimal_values():
    assert _jsonable("text") == "text"
    assert _jsonable(None) is None
    assert _jsonable(7) == 7


async def test_execute_readonly_returns_rows_and_columns(readonly_pool):
    result = await execute_readonly(
        readonly_pool, "SELECT 1 AS one, 'x' AS two", None, 10, 15000
    )
    assert result.columns == [
        {"name": "one", "type": "int4"},
        {"name": "two", "type": "text"},
    ]
    assert result.rows == [[1, "x"]]
    assert result.row_count == 1
    assert result.truncated is False
    assert result.roundtrip_ms > 0


async def test_execute_readonly_truncates_at_requested_row_limit(readonly_pool):
    result = await execute_readonly(
        readonly_pool, "SELECT * FROM generate_series(1, 10)", None, 3, 15000
    )
    assert result.row_count == 3
    assert result.truncated is True


async def test_execute_readonly_caps_row_limit_at_max_row_limit(readonly_pool):
    # A client asking for far more than MAX_ROW_LIMIT must still be
    # clamped before the request ever reaches Postgres.
    result = await execute_readonly(
        readonly_pool, "SELECT * FROM generate_series(1, 60000)", None, 1_000_000, 15000
    )
    assert result.row_count == MAX_ROW_LIMIT
    assert result.truncated is True


async def test_execute_readonly_rejects_write_statement_with_structured_error(
    readonly_pool,
):
    with pytest.raises(QueryExecutionError) as exc_info:
        await execute_readonly(
            readonly_pool, "DELETE FROM museum_network.tickets", None, 10, 15000
        )
    assert exc_info.value.info.sqlstate == "25006"  # read_only_sql_transaction


async def test_execute_readonly_reports_structured_error_for_bad_sql(readonly_pool):
    with pytest.raises(QueryExecutionError) as exc_info:
        await execute_readonly(
            readonly_pool, "SELECT * FROM no_such_table_xyz", None, 10, 15000
        )
    info = exc_info.value.info
    assert info.sqlstate == "42P01"
    assert "no_such_table_xyz" in info.message
    assert info.position is not None

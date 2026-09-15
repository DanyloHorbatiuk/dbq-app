"""Unit tests for app.security.validate_readonly_sql — SPEC.md §ФВ-03's
negative tests, plus the positive cases that must keep working. Pure
text tokenizer/validator: no database connection needed.
"""

import pytest

from app.security import SqlValidationError, validate_readonly_sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "  SELECT 1  ",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "TABLE museum_network.halls",
        "VALUES (1), (2)",
        "EXPLAIN SELECT 1",
        "EXPLAIN (ANALYZE, BUFFERS) SELECT 1",
        "SELECT ';' AS x",
        "SELECT 1 -- comment ; still one statement\n",
        "SELECT '/* not a real comment */'",
        "/* leading comment */ SELECT 1",
        "SELECT $$literal ; semicolon$$",
        "SELECT 1;",
        "SELECT 1;   ",
    ],
)
def test_valid_statements_pass(sql):
    validate_readonly_sql(sql)  # must not raise


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE museum_network.tickets",
        "INSERT INTO museum_network.tickets VALUES (1)",
        "UPDATE museum_network.tickets SET quantity = 1",
        "DELETE FROM museum_network.tickets",
        "COPY (SELECT 1) TO PROGRAM 'ls'",
        "SET statement_timeout = 1",
        "",
        "   ",
    ],
)
def test_disallowed_statements_are_rejected(sql):
    with pytest.raises(SqlValidationError):
        validate_readonly_sql(sql)


def test_multiple_statements_via_semicolon_rejected():
    with pytest.raises(SqlValidationError, match="один SQL-оператор"):
        validate_readonly_sql("SELECT 1; SELECT 2")


def test_semicolon_inside_string_literal_is_not_a_statement_boundary():
    # The exact case CLAUDE.md calls out: a naive ";".split() would
    # wrongly see two statements here.
    result = validate_readonly_sql("SELECT ';' AS separator")
    assert result == "SELECT ';' AS separator"


def test_explain_analyze_over_insert_is_rejected():
    # EXPLAIN ANALYZE genuinely executes the statement it wraps, so it
    # must not become a backdoor around the SELECT-only restriction.
    with pytest.raises(SqlValidationError, match="EXPLAIN"):
        validate_readonly_sql("EXPLAIN (ANALYZE) INSERT INTO x VALUES (1)")


def test_explain_over_update_is_rejected():
    with pytest.raises(SqlValidationError):
        validate_readonly_sql("EXPLAIN UPDATE museum_network.tickets SET quantity = 1")


def test_bare_explain_analyze_without_parens_is_rejected():
    # Documents actual, current scope: only the parenthesized EXPLAIN
    # option list ("EXPLAIN (ANALYZE) ...") is recognized as wrapping a
    # SELECT/WITH/TABLE/VALUES; the older bare-keyword form
    # "EXPLAIN ANALYZE ..." falls through to the same rejection.
    with pytest.raises(SqlValidationError):
        validate_readonly_sql("EXPLAIN ANALYZE SELECT 1")


def test_nested_block_comments_are_handled():
    # PostgreSQL nests /* */ unlike standard SQL.
    validate_readonly_sql("SELECT 1 /* outer /* inner */ still outer */")

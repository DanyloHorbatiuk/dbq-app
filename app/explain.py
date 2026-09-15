"""Runs EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON) and flattens
the resulting plan tree into a list of nodes — SPEC.md §ФВ-04.

Reuses executor.py's READ ONLY + statement_timeout guarantees: EXPLAIN
ANALYZE genuinely executes the statement it wraps, so this module never
runs anything security.validate_readonly_sql() hasn't already cleared
for arbitrary SQL, or that isn't trusted catalog text — exactly the same
trust boundary as execute_readonly().
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg import sql as psql
from psycopg_pool import AsyncConnectionPool

from app.executor import QueryExecutionError, extract_error_info

# "похибка оцінки понад 10-кратну" (SPEC.md §ФВ-04) — a node's actual row
# count more than 10x its estimate gets flagged.
ESTIMATION_ERROR_THRESHOLD = 10.0


@dataclass
class PlanNode:
    node_type: str
    depth: int
    plan_rows: float
    actual_rows: float | None
    actual_loops: int | None
    actual_total_time_ms: float | None
    self_time_ms: float | None
    estimation_error: float | None
    misestimated: bool


@dataclass
class ExplainResult:
    plan: Any  # the raw "Plan" subtree from EXPLAIN (FORMAT JSON)
    nodes: list[PlanNode]
    planning_ms: float | None
    execution_ms: float | None
    node_types: list[str]
    slowest_node: PlanNode | None
    estimation_error: float | None  # max over the whole tree


async def explain_query(
    pool: AsyncConnectionPool,
    sql_text: str,
    parameters: dict[str, Any] | None,
    statement_timeout_ms: int,
    analyze: bool,
    buffers: bool,
) -> ExplainResult:
    # Options come only from this fixed, hardcoded vocabulary — never
    # from a client-supplied string — so splicing them into the SQL text
    # carries the same "not user data" reasoning as
    # routers/meta.py's _SERVER_INFO_QUERY. sql_text itself isn't
    # re-validated here: it arrives already trusted (catalog YAML) or
    # already checked by security.validate_readonly_sql() in
    # routers/execute.py or routers/explain.py — wrapping it in EXPLAIN
    # doesn't change what that text is.
    options = ["FORMAT JSON", "SETTINGS"]
    if analyze:
        options.append("ANALYZE")
    if buffers:
        options.append("BUFFERS")
    explain_sql = f"EXPLAIN ({', '.join(options)}) {sql_text}"

    try:
        async with pool.connection() as conn, conn.transaction():
            await conn.execute("SET TRANSACTION READ ONLY")
            await conn.execute(
                psql.SQL("SET LOCAL statement_timeout = {}").format(
                    psql.Literal(statement_timeout_ms)
                )
            )
            cur = await conn.execute(explain_sql, parameters or None)
            row = await cur.fetchone()
    except psycopg.Error as exc:
        raise QueryExecutionError(extract_error_info(exc)) from exc

    # EXPLAIN (FORMAT JSON) always returns a single-element array under
    # the "QUERY PLAN" column; psycopg decodes the json column natively.
    payload = row["QUERY PLAN"][0]
    plan_tree = payload["Plan"]

    nodes = list(_flatten(plan_tree, depth=0))
    # By self_time_ms, not the raw "Actual Total Time" Postgres reports:
    # that field is *cumulative*, it already includes every descendant's
    # time, so the root node mechanically has the largest (or joint
    # largest) value in any tree — picking "slowest" by it would almost
    # always just point back at the root and never at the real
    # bottleneck. self_time_ms already subtracted children's time (and
    # multiplied by loops) in _flatten() specifically so this pick means
    # something.
    timed = [n for n in nodes if n.self_time_ms is not None]
    errored = [n.estimation_error for n in nodes if n.estimation_error is not None]

    return ExplainResult(
        plan=plan_tree,
        nodes=nodes,
        planning_ms=payload.get("Planning Time"),
        execution_ms=payload.get("Execution Time"),
        node_types=sorted({n.node_type for n in nodes}),
        slowest_node=max(timed, key=lambda n: n.self_time_ms or 0.0, default=None),
        estimation_error=max(errored, default=None),
    )


def _flatten(node: dict[str, Any], depth: int) -> Iterator[PlanNode]:
    plan_rows = float(node.get("Plan Rows", 0))
    has_actual = "Actual Rows" in node

    actual_rows: float | None = None
    actual_loops: int | None = None
    actual_total_time: float | None = None
    self_time_ms: float | None = None
    estimation_error: float | None = None
    misestimated = False

    if has_actual:
        actual_rows = float(node["Actual Rows"])
        actual_loops = int(node.get("Actual Loops", 1))
        actual_total_time = node.get("Actual Total Time")

        if actual_total_time is not None:
            # "врахування loops при підсумовуванні часу" (SPEC.md
            # §ФВ-04): Actual Total Time is Postgres's *per-loop average*
            # for this node, so a node re-executed by a nested loop needs
            # multiplying by its own loop count before it's comparable to
            # (or summed with) any other node's time.
            total_time_all_loops = actual_total_time * actual_loops
            children_total = sum(
                (child.get("Actual Total Time") or 0.0) * child.get("Actual Loops", 1)
                for child in node.get("Plans", [])
                if "Actual Total Time" in child
            )
            self_time_ms = max(0.0, total_time_all_loops - children_total)

        # actual/estimated, the same direction SPEC.md §ФВ-02 defines for
        # plan_summary.estimation_error — max(plan_rows, 1) avoids a
        # divide-by-zero when the planner estimated 0 rows.
        estimation_error = round(actual_rows / max(plan_rows, 1.0), 2)
        misestimated = estimation_error > ESTIMATION_ERROR_THRESHOLD

    yield PlanNode(
        node_type=node["Node Type"],
        depth=depth,
        plan_rows=plan_rows,
        actual_rows=actual_rows,
        actual_loops=actual_loops,
        actual_total_time_ms=actual_total_time,
        self_time_ms=self_time_ms,
        estimation_error=estimation_error,
        misestimated=misestimated,
    )

    for child in node.get("Plans", []):
        yield from _flatten(child, depth + 1)

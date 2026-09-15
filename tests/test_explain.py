"""Unit tests for app.explain._flatten's plan-tree walk against a
hand-built EXPLAIN (FORMAT JSON) fragment, plus one integration test
against a real EXPLAIN ANALYZE.
"""

from app.explain import ESTIMATION_ERROR_THRESHOLD, _flatten, explain_query

# Actual Total Time is Postgres's *per-loop average*, so the Index Scan
# leaf (5ms average, 3 loops) really cost 15ms total — the same as its
# parent's 50ms minus the Seq Scan's 20ms leaves for it.
_SAMPLE_PLAN = {
    "Node Type": "Hash Join",
    "Plan Rows": 100,
    "Actual Rows": 90,
    "Actual Loops": 1,
    "Actual Total Time": 50.0,
    "Plans": [
        {
            "Node Type": "Seq Scan",
            "Plan Rows": 1000,
            "Actual Rows": 1000,
            "Actual Loops": 1,
            "Actual Total Time": 20.0,
            "Plans": [],
        },
        {
            "Node Type": "Index Scan",
            "Plan Rows": 5,
            "Actual Rows": 500,
            "Actual Loops": 3,
            "Actual Total Time": 5.0,
            "Plans": [],
        },
    ],
}


def test_flatten_visits_every_node_depth_first():
    nodes = list(_flatten(_SAMPLE_PLAN, depth=0))
    assert [n.node_type for n in nodes] == ["Hash Join", "Seq Scan", "Index Scan"]
    assert [n.depth for n in nodes] == [0, 1, 1]


def test_self_time_subtracts_children_total():
    root = list(_flatten(_SAMPLE_PLAN, depth=0))[0]
    # 50ms total minus (20ms Seq Scan + 5ms*3 loops Index Scan) = 15ms
    assert root.self_time_ms == 15.0


def test_self_time_multiplies_leaf_time_by_loop_count():
    nodes = list(_flatten(_SAMPLE_PLAN, depth=0))
    index_scan = nodes[2]
    assert index_scan.actual_total_time_ms == 5.0
    assert index_scan.actual_loops == 3
    assert index_scan.self_time_ms == 15.0  # 5ms average * 3 loops


def test_estimation_error_and_misestimated_flag():
    nodes = list(_flatten(_SAMPLE_PLAN, depth=0))
    index_scan = nodes[2]
    assert index_scan.estimation_error == 100.0  # 500 actual / 5 estimated
    assert index_scan.estimation_error > ESTIMATION_ERROR_THRESHOLD
    assert index_scan.misestimated is True

    seq_scan = nodes[1]
    assert seq_scan.estimation_error == 1.0
    assert seq_scan.misestimated is False


def test_flatten_without_analyze_leaves_actual_fields_none():
    plan_only = {"Node Type": "Seq Scan", "Plan Rows": 42, "Plans": []}
    node = next(_flatten(plan_only, depth=0))
    assert node.actual_rows is None
    assert node.actual_loops is None
    assert node.self_time_ms is None
    assert node.misestimated is False


async def test_explain_query_against_real_database(readonly_pool):
    result = await explain_query(
        readonly_pool,
        "SELECT * FROM museum_network.halls",
        None,
        15000,
        analyze=True,
        buffers=True,
    )
    assert result.nodes
    assert result.execution_ms is not None
    assert result.planning_ms is not None
    assert any("Scan" in nt for nt in result.node_types)

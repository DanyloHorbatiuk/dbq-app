"""Unit tests for app.benchmark's pure statistics helpers, plus
integration tests that run_benchmark() follows CLAUDE.md's fixed
methodology (first run set aside as cold, discard_first controls
whether it counts toward the reported stats).
"""

import pytest

from app.benchmark import _compute_stats, _percentile, run_benchmark


def test_compute_stats_basic_values():
    stats = _compute_stats([10.0, 20.0, 30.0, 40.0, 50.0])
    assert stats.min_ms == 10.0
    assert stats.max_ms == 50.0
    assert stats.median_ms == 30.0
    assert stats.mean_ms == 30.0
    assert stats.p95_ms == pytest.approx(48.0)
    assert stats.stddev_ms == pytest.approx(15.8113883, rel=1e-6)


def test_compute_stats_single_sample_has_zero_stddev():
    stats = _compute_stats([42.0])
    assert stats.stddev_ms == 0.0
    assert stats.min_ms == stats.max_ms == stats.median_ms == 42.0


def test_percentile_linear_interpolation():
    assert _percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.95) == pytest.approx(4.8)


def test_percentile_single_sample_returns_that_sample():
    assert _percentile([7.0], 0.95) == 7.0


async def test_run_benchmark_discards_cold_run_by_default(readonly_pool):
    result = await run_benchmark(readonly_pool, "SELECT 1", None, 10, 15000, 3, True)
    assert result.runs == 3
    assert len(result.samples_ms) == 2  # cold run excluded from the reported stats
    assert result.stats.median_ms >= 0


async def test_run_benchmark_keeps_all_runs_when_discard_first_false(readonly_pool):
    result = await run_benchmark(readonly_pool, "SELECT 1", None, 10, 15000, 3, False)
    assert len(result.samples_ms) == 3

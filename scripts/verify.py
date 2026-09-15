"""make verify — checks SPEC.md §7 acceptance criteria against a live
system and prints the §7.2 report (catalog counts, SQL coverage, table
volumes, test count). The individual checks live in scripts/verify_checks.py;
this module only orchestrates them in §7's own order and prints the
PASS/FAIL summary.

Never fudges a criterion to force a green result (CLAUDE.md: "Ніколи не
пиши 'має працювати'"): exits 0 only if every criterion actually passes,
1 otherwise, with each failure named in the summary.
"""

from __future__ import annotations

import asyncio
import sys

from app.catalog import DEFAULT_CATALOG_ROOT, compute_coverage, load_catalog
from app.config import get_settings
from scripts import verify_checks as checks
from scripts.verify_report import Report

_CATALOG_MIN_TOTAL = 55  # SPEC.md §7.4
_CATALOG_MIN_LEVEL3 = 20
_CATALOG_MIN_VARIANT_PAIRS = 6  # SPEC.md §3.1


async def main() -> int:
    report = Report()
    settings = get_settings()
    catalog = load_catalog(DEFAULT_CATALOG_ROOT)

    print("=== SPEC.md §7 — критерії приймання ===\n")

    readonly_pools = {
        database: checks.pool_for(settings, database, "readonly")
        for database in ("museum", "dvdrental")
    }
    for pool in readonly_pools.values():
        await pool.open()
    admin_pool = checks.pool_for(
        settings, "museum", "admin"
    )  # only museum runs experiments
    await admin_pool.open()
    db_ok = await checks.check_db_reachable(readonly_pools, report)

    report.info("\n--- Звіт: каталог, покриття, обсяги, тести (§7.2) ---")
    checks.print_catalog_counts(catalog, report)
    coverage = compute_coverage(catalog)
    checks.write_coverage_csv(coverage)
    report.check(
        "Покриття можливостей SQL — 100%",
        coverage["coverage_pct"] == 100.0,
        f"{coverage['covered_features']}/{coverage['total_features']}",
    )
    if db_ok:
        table_sizes = await checks.fetch_table_sizes(readonly_pools)
        checks.write_table_sizes_csv(table_sizes)
    test_count, tests_passed = checks.run_test_suite()
    report.check(
        f"Тестів: {test_count} (мінімум {checks.MIN_TESTS})",
        test_count >= checks.MIN_TESTS and tests_passed,
        "усі пройшли" if tests_passed else "є провалені тести — див. вивід pytest вище",
    )

    report.info("\n--- Обсяги даних museum (§2.2.6, §7.3) ---")
    if db_ok:
        await checks.check_museum_volumes(readonly_pools["museum"], report)
    else:
        report.check("Обсяги даних museum", False, "БД недоступна")

    report.info("\n--- Розмір каталогу (§3.1, §7.4) ---")
    total = len(catalog)
    level3 = sum(1 for e in catalog.values() if e.level == 3)
    variant_pairs = sum(1 for e in catalog.values() if e.variants)
    report.check(
        f"Запитів у каталозі: {total} (мінімум {_CATALOG_MIN_TOTAL})",
        total >= _CATALOG_MIN_TOTAL,
    )
    report.check(
        f"Запитів 3-го рівня: {level3} (мінімум {_CATALOG_MIN_LEVEL3})",
        level3 >= _CATALOG_MIN_LEVEL3,
    )
    report.check(
        f"Пар варіантів: {variant_pairs} (мінімум {_CATALOG_MIN_VARIANT_PAIRS})",
        variant_pairs >= _CATALOG_MIN_VARIANT_PAIRS,
    )

    report.info("\n--- Кожен запит каталогу виконується (§7.5) ---")
    if db_ok:
        await checks.check_catalog_runs(catalog, readonly_pools, report)
    else:
        report.check("Виконання каталогу", False, "БД недоступна")

    report.info("\n--- Експерименти з індексами (§ФВ-06, §7.6) ---")
    if db_ok:
        await checks.check_index_experiments(
            catalog, admin_pool, readonly_pools["museum"], settings, report
        )
    else:
        report.check("Експерименти з індексами", False, "БД недоступна")

    report.info("\n--- reports/benchmarks.csv (§7.7) ---")
    checks.check_benchmarks_csv(report)

    for pool in readonly_pools.values():
        await pool.close()
    await admin_pool.close()

    print("\n=== Підсумок ===")
    if report.failures:
        print(f"НЕ ПРОЙДЕНО ({len(report.failures)} з критеріїв):")
        for failure in report.failures:
            print(f"  - {failure}")
        return 1
    print("Усі критерії пройдено.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

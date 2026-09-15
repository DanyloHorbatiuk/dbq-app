"""Loads and validates the YAML query catalog (SPEC.md §3.3) once, at
startup. A single bad file must fail loudly and clearly — ROADMAP.md's
own Etap 5 check corrupts one YAML and expects the app to refuse to
start with a readable message, not a raw traceback.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.models import QueryDefinition

logger = logging.getLogger(__name__)

DEFAULT_CATALOG_ROOT = Path(__file__).resolve().parent.parent / "queries"

# The control list behind GET /api/meta/coverage — one entry per SQL
# capability SPEC.md §3.2 names for that level. This is our own concrete
# vocabulary for what SPEC.md describes in prose; sql_features in catalog
# YAML files are expected to draw from it (not enforced by the schema —
# free-text tags stay useful for capabilities this list doesn't
# anticipate — but coverage can only ever measure against a fixed list).
SQL_FEATURE_CHECKLIST: dict[int, list[str]] = {
    1: [
        "where",
        "order_by",
        "limit",
        "distinct",
        "case",
        "coalesce",
        "date_function",
        "string_function",
    ],
    2: [
        "join_inner",
        "join_left",
        "join_right",
        "join_full",
        "group_by",
        "having",
        "aggregate",
        "union",
        "intersect",
        "except",
        "subquery_scalar",
        "subquery_correlated",
        "exists",
        "in",
        "any",
    ],
    3: [
        "cte",
        "recursive_cte",
        "window_function",
        "lateral",
        "grouping_sets",
        "rollup",
        "cube",
        "filter",
        "percentile_cont",
        "json_agg",
    ],
    4: [
        "rfm_segmentation",
        "cohort_analysis",
        "abc_analysis",
        "top_n_in_group",
        "seasonality",
        "anomaly_detection",
    ],
}


class CatalogError(RuntimeError):
    """Raised when the query catalog fails to load."""


def load_catalog(root: Path) -> dict[str, QueryDefinition]:
    """Reads every queries/<database>/level<N>/*.yaml file under root,
    validates it, and returns it keyed by id. Stops at the first problem
    found — a partially loaded catalog would be more confusing to debug
    than refusing to start at all."""
    yaml_files = sorted(root.glob("*/level*/*.yaml"))
    if not yaml_files:
        raise CatalogError(f"No catalog YAML files found under {root}")

    catalog: dict[str, QueryDefinition] = {}
    sources: dict[str, Path] = {}

    for path in yaml_files:
        entry = _load_one(path)
        _check_directory_matches(path, entry)

        if entry.id in catalog:
            raise CatalogError(
                f"{path}: duplicate catalog id '{entry.id}' "
                f"(already used by {sources[entry.id]})"
            )
        catalog[entry.id] = entry
        sources[entry.id] = path

    logger.info("Loaded %d catalog queries from %s", len(catalog), root)
    return catalog


def _load_one(path: Path) -> QueryDefinition:
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CatalogError(f"{path}: invalid YAML — {exc}") from exc

    if not isinstance(raw, dict):
        raise CatalogError(f"{path}: expected a YAML mapping at the top level")

    try:
        return QueryDefinition.model_validate(raw)
    except ValidationError as exc:
        raise CatalogError(f"{path}: schema validation failed:\n{exc}") from exc


def _check_directory_matches(path: Path, entry: QueryDefinition) -> None:
    """Catches the common authoring mistake of a file sitting in the
    wrong queries/<database>/level<N>/ folder for what its own database/
    level fields say — cheap to check, confusing to debug otherwise."""
    dir_database = path.parent.parent.name
    dir_level = path.parent.name
    if entry.database != dir_database:
        raise CatalogError(
            f"{path}: database '{entry.database}' does not match directory '{dir_database}'"
        )
    if dir_level != f"level{entry.level}":
        raise CatalogError(
            f"{path}: level {entry.level} does not match directory '{dir_level}'"
        )


@lru_cache
def get_catalog() -> dict[str, QueryDefinition]:
    """Cached singleton: the catalog is read from disk once per process."""
    return load_catalog(DEFAULT_CATALOG_ROOT)


def compute_coverage(catalog: dict[str, QueryDefinition]) -> dict[str, Any]:
    """Which SQL_FEATURE_CHECKLIST entries at least one catalog query
    covers, and how many queries cover each — GET /api/meta/coverage
    (SPEC.md §ФВ-11), also the check CLAUDE.md asks to run before adding
    a new catalog query ("не п'ятий варіант GROUP BY")."""
    counts: dict[str, int] = {}
    for entry in catalog.values():
        for feature in entry.sql_features:
            counts[feature] = counts.get(feature, 0) + 1

    by_level: dict[str, Any] = {}
    total = 0
    total_covered = 0
    for level, features in SQL_FEATURE_CHECKLIST.items():
        covered = [f for f in features if f in counts]
        by_level[str(level)] = {
            "total": len(features),
            "covered": len(covered),
            "missing": sorted(set(features) - counts.keys()),
            "counts": {f: counts[f] for f in covered},
        }
        total += len(features)
        total_covered += len(covered)

    return {
        "total_features": total,
        "covered_features": total_covered,
        "coverage_pct": round(100 * total_covered / total, 1) if total else 0.0,
        "by_level": by_level,
    }

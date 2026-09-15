"""Unit tests for app.catalog: loading, validation, coverage computation,
and variant resolution. Reads straight from disk — no database needed,
matching ROADMAP.md's own Etap 5 check ("зіпсувати один YAML — застосунок
має не запуститися зі зрозумілим повідомленням").
"""

from pathlib import Path

import pytest

from app.catalog import (
    DEFAULT_CATALOG_ROOT,
    CatalogError,
    compute_coverage,
    load_catalog,
    resolve_variant_sql,
)


def test_real_catalog_loads_without_error():
    catalog = load_catalog(DEFAULT_CATALOG_ROOT)
    assert len(catalog) > 0


def test_every_entry_id_matches_its_dict_key():
    catalog = load_catalog(DEFAULT_CATALOG_ROOT)
    for key, entry in catalog.items():
        assert key == entry.id


def test_museum_catalog_meets_spec_minimum_of_25_queries():
    # dvdrental is still empty (see TODO.md), so this only checks what
    # museum alone owes per SPEC.md §3.1.
    catalog = load_catalog(DEFAULT_CATALOG_ROOT)
    museum_entries = [e for e in catalog.values() if e.database == "museum"]
    assert len(museum_entries) >= 25


def test_at_least_six_variant_pairs_exist():
    catalog = load_catalog(DEFAULT_CATALOG_ROOT)
    pairs = [e for e in catalog.values() if e.variants]
    assert len(pairs) >= 6


def test_coverage_is_complete_for_current_catalog():
    catalog = load_catalog(DEFAULT_CATALOG_ROOT)
    coverage = compute_coverage(catalog)
    assert coverage["covered_features"] == coverage["total_features"]
    assert coverage["coverage_pct"] == 100.0


def test_resolve_variant_sql_returns_main_sql_by_default():
    catalog = load_catalog(DEFAULT_CATALOG_ROOT)
    entry = next(e for e in catalog.values() if e.variants)
    assert resolve_variant_sql(entry, None) == entry.sql


def test_resolve_variant_sql_returns_variant_by_index():
    catalog = load_catalog(DEFAULT_CATALOG_ROOT)
    entry = next(e for e in catalog.values() if e.variants)
    assert resolve_variant_sql(entry, 0) == entry.variants[0].sql


def test_resolve_variant_sql_rejects_out_of_range_index():
    catalog = load_catalog(DEFAULT_CATALOG_ROOT)
    entry = next(e for e in catalog.values() if e.variants)
    with pytest.raises(IndexError):
        resolve_variant_sql(entry, len(entry.variants))


def test_duplicate_id_is_rejected(tmp_path: Path):
    _write_minimal_query(tmp_path, "dup", "dup-a.yaml")
    _write_minimal_query(tmp_path, "dup", "dup-b.yaml")
    with pytest.raises(CatalogError, match="duplicate catalog id"):
        load_catalog(tmp_path)


def test_query_in_wrong_level_directory_is_rejected(tmp_path: Path):
    directory = tmp_path / "museum" / "level1"
    directory.mkdir(parents=True)
    (directory / "wrong.yaml").write_text(
        "id: wrong\ndatabase: museum\nlevel: 2\ntitle: t\nbusiness_question: q\n"
        "sql_features: [where]\nsql: SELECT 1\n",
        encoding="utf-8",
    )
    with pytest.raises(CatalogError, match="does not match directory"):
        load_catalog(tmp_path)


def test_invalid_yaml_is_rejected(tmp_path: Path):
    directory = tmp_path / "museum" / "level1"
    directory.mkdir(parents=True)
    (directory / "broken.yaml").write_text(
        "id: [this is not valid: yaml", encoding="utf-8"
    )
    with pytest.raises(CatalogError):
        load_catalog(tmp_path)


def test_missing_required_field_is_rejected(tmp_path: Path):
    directory = tmp_path / "museum" / "level1"
    directory.mkdir(parents=True)
    (directory / "incomplete.yaml").write_text(
        "id: incomplete\ndatabase: museum\nlevel: 1\ntitle: t\n", encoding="utf-8"
    )
    with pytest.raises(CatalogError, match="schema validation failed"):
        load_catalog(tmp_path)


def _write_minimal_query(root: Path, entry_id: str, filename: str) -> None:
    directory = root / "museum" / "level1"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_text(
        f"id: {entry_id}\ndatabase: museum\nlevel: 1\n"
        "title: t\nbusiness_question: q\nsql_features: [where]\nsql: SELECT 1\n",
        encoding="utf-8",
    )

"""Index experiments — SPEC.md §ФВ-06/§ФВ-07: loads and validates
experiments/*.yaml once, mirroring app.catalog's load-at-startup
pattern exactly (same fail-loudly contract via ExperimentError). Running
an experiment is app.experiment_runner's job, kept in its own module for
the same reason executor.py/benchmark.py/explain.py are separate from
app.catalog — this module only knows how to read and validate the YAML.

Pydantic models for the YAML schema live here rather than in
app/models.py: that module is already near CLAUDE.md's ~250-line
guideline, and these shapes are only ever consumed by this module and
app.experiment_runner, not by anything that already imports app.models.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

DEFAULT_EXPERIMENTS_ROOT = Path(__file__).resolve().parent.parent / "experiments"


class IndexExperiment(BaseModel):
    id: str
    kind: Literal["index"] = "index"
    database: Literal["dvdrental", "museum"]
    title: str
    query_id: str
    table_name: str
    index_name: str
    create_sql: str
    description: str | None = None


class ViewVsMatviewExperiment(BaseModel):
    id: str
    kind: Literal["view_vs_matview"]
    database: Literal["dvdrental", "museum"]
    title: str
    matview_name: str
    refresh_sql: str
    sql_view: str
    sql_matview: str
    description: str | None = None


Experiment = Annotated[
    IndexExperiment | ViewVsMatviewExperiment, Field(discriminator="kind")
]
_ExperimentAdapter: TypeAdapter[Experiment] = TypeAdapter(Experiment)


class ExperimentError(RuntimeError):
    """Raised when experiments/*.yaml fails to load — same "fail loudly
    at startup" contract as app.catalog.CatalogError."""


def load_experiments(root: Path) -> dict[str, Experiment]:
    experiments: dict[str, Experiment] = {}
    sources: dict[str, Path] = {}

    for path in sorted(root.glob("*.yaml")):
        try:
            raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ExperimentError(f"{path}: invalid YAML — {exc}") from exc
        if not isinstance(raw, dict):
            raise ExperimentError(f"{path}: expected a YAML mapping at the top level")

        raw.setdefault("kind", "index")
        try:
            experiment = _ExperimentAdapter.validate_python(raw)
        except ValidationError as exc:
            raise ExperimentError(f"{path}: schema validation failed:\n{exc}") from exc

        if experiment.id in experiments:
            raise ExperimentError(
                f"{path}: duplicate experiment id '{experiment.id}' "
                f"(already used by {sources[experiment.id]})"
            )
        experiments[experiment.id] = experiment
        sources[experiment.id] = path

    return experiments


@lru_cache
def get_experiments() -> dict[str, Experiment]:
    return load_experiments(DEFAULT_EXPERIMENTS_ROOT)

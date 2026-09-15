"""Pydantic models for the YAML query catalog — SPEC.md §3.3 defines this
exact schema; a query is invalid if it doesn't match it, full stop.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Database = Literal["dvdrental", "museum"]
ChartType = Literal["bar", "line", "pie", "scatter", "none"]
ParameterType = Literal["number", "string", "date"]


class ChartHint(BaseModel):
    """Tells the frontend how to plot a result set (SPEC.md §ФВ-09)."""

    type: ChartType
    x: str | None = None
    y: list[str] = Field(default_factory=list)
    secondary_y: str | None = None


class QueryParameter(BaseModel):
    """A %(name)s placeholder the SQL text substitutes via psycopg
    parameterization — never string formatting (CLAUDE.md security rule)."""

    name: str
    type: ParameterType
    default: float | str | None = None


class QueryVariant(BaseModel):
    """An alternative formulation of the same query, for plan comparison
    (SPEC.md §3.1 requires at least 6 such pairs)."""

    label: str
    sql: str


class QueryDefinition(BaseModel):
    """One catalog entry — one YAML file under queries/<database>/level<N>/.

    id, database, level, title, business_question, sql_features, sql are
    required by SPEC.md §3.3; everything else is optional metadata.
    """

    id: str
    database: Database
    level: int = Field(ge=1, le=4)
    title: str
    business_question: str
    sql_features: list[str]
    sql: str
    description: str | None = None
    expected_insight: str | None = None
    chart: ChartHint | None = None
    parameters: list[QueryParameter] = Field(default_factory=list)
    variants: list[QueryVariant] = Field(default_factory=list)

    @field_validator("sql_features")
    @classmethod
    def _non_empty_features(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("sql_features must list at least one SQL capability")
        return value


class CatalogEntrySummary(BaseModel):
    """Slim shape for GET /api/catalog — metadata only, no SQL text
    (SPEC.md §ФВ-01: the full text only comes back from
    GET /api/catalog/{id})."""

    id: str
    database: Database
    level: int
    title: str
    business_question: str
    sql_features: list[str]


class ExecuteRequest(BaseModel):
    """POST /api/execute body — SPEC.md §ФВ-02/§ФВ-03: either a catalog
    query_id (trusted, authored SQL) or raw sql + database (validated by
    app.security before it ever reaches the executor), never both."""

    query_id: str | None = None
    sql: str | None = None
    database: Database | None = None
    variant: int | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    row_limit: int | None = None
    with_plan: bool = False

    @model_validator(mode="after")
    def _check_source(self) -> "ExecuteRequest":
        if bool(self.query_id) == bool(self.sql):
            raise ValueError("Provide exactly one of query_id or sql.")
        if self.sql is not None and self.database is None:
            raise ValueError("database is required when sql is provided.")
        return self


class ColumnInfo(BaseModel):
    name: str
    type: str


class ExecuteTimings(BaseModel):
    roundtrip_ms: float
    # planning_ms/execution_ms come from EXPLAIN ANALYZE (SPEC.md §ФВ-02),
    # filled in by app.explain when with_plan=true — None otherwise.
    planning_ms: float | None = None
    execution_ms: float | None = None


class PlanNodeOut(BaseModel):
    """One flattened plan-tree node — SPEC.md §ФВ-04."""

    node_type: str
    depth: int
    plan_rows: float
    actual_rows: float | None
    actual_loops: int | None
    actual_total_time_ms: float | None
    self_time_ms: float | None
    estimation_error: float | None
    misestimated: bool


class PlanSummary(BaseModel):
    node_types: list[str]
    slowest_node: PlanNodeOut | None
    estimation_error: float | None


class ExecuteResponse(BaseModel):
    query_id: str | None = None
    columns: list[ColumnInfo]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    timings: ExecuteTimings
    plan: Any = None
    plan_summary: PlanSummary | None = None


class ExplainRequest(BaseModel):
    """POST /api/explain body — SPEC.md §ФВ-04. Same query_id/sql
    resolution rules as ExecuteRequest."""

    query_id: str | None = None
    sql: str | None = None
    database: Database | None = None
    variant: int | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    analyze: bool = True
    buffers: bool = True

    @model_validator(mode="after")
    def _check_source(self) -> "ExplainRequest":
        if bool(self.query_id) == bool(self.sql):
            raise ValueError("Provide exactly one of query_id or sql.")
        if self.sql is not None and self.database is None:
            raise ValueError("database is required when sql is provided.")
        return self


class ExplainResponse(BaseModel):
    query_id: str | None = None
    plan: Any
    nodes: list[PlanNodeOut]
    planning_ms: float | None
    execution_ms: float | None
    plan_summary: PlanSummary


class BenchmarkRequest(BaseModel):
    """POST /api/benchmark body — SPEC.md §ФВ-05. Same query_id/sql
    resolution rules as ExecuteRequest. cold_cache is accepted for
    parity with SPEC.md's example payload but is a no-op — see
    app.benchmark.run_benchmark's docstring for why a real cache flush
    isn't something a read-only API can safely do."""

    query_id: str | None = None
    sql: str | None = None
    database: Database | None = None
    variant: int | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    runs: int | None = Field(default=None, ge=2, le=100)
    discard_first: bool = True
    cold_cache: bool = False
    row_limit: int | None = None

    @model_validator(mode="after")
    def _check_source(self) -> "BenchmarkRequest":
        if bool(self.query_id) == bool(self.sql):
            raise ValueError("Provide exactly one of query_id or sql.")
        if self.sql is not None and self.database is None:
            raise ValueError("database is required when sql is provided.")
        return self


class BenchmarkStatsOut(BaseModel):
    min_ms: float
    median_ms: float
    mean_ms: float
    p95_ms: float
    max_ms: float
    stddev_ms: float


class EnvironmentInfo(BaseModel):
    server_version: str
    shared_buffers: str
    work_mem: str
    random_page_cost: str
    table_sizes: dict[str, str]


class BenchmarkResponse(BaseModel):
    query_id: str | None = None
    runs: int
    cold_run_ms: float
    stats: BenchmarkStatsOut
    samples_ms: list[float]
    environment: EnvironmentInfo

"""Pydantic models for the YAML query catalog — SPEC.md §3.3 defines this
exact schema; a query is invalid if it doesn't match it, full stop.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

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

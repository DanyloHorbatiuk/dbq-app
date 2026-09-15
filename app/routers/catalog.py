"""GET /api/catalog, GET /api/catalog/{query_id} — SPEC.md §ФВ-01."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.catalog import get_catalog
from app.models import CatalogEntrySummary, Database, QueryDefinition

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("")
async def list_catalog(
    database: Database | None = None,
    level: Annotated[int | None, Query(ge=1, le=4)] = None,
    feature: str | None = None,
    q: str | None = None,
) -> list[CatalogEntrySummary]:
    """Filtered, SQL-text-free listing — the SQL itself only comes back
    from GET /api/catalog/{id}, per SPEC.md §ФВ-01."""
    entries: list[QueryDefinition] = list(get_catalog().values())

    if database is not None:
        entries = [e for e in entries if e.database == database]
    if level is not None:
        entries = [e for e in entries if e.level == level]
    if feature is not None:
        entries = [e for e in entries if feature in e.sql_features]
    if q is not None:
        needle = q.casefold()
        entries = [
            e
            for e in entries
            if needle in e.title.casefold() or needle in e.business_question.casefold()
        ]

    return [
        CatalogEntrySummary(
            id=e.id,
            database=e.database,
            level=e.level,
            title=e.title,
            business_question=e.business_question,
            sql_features=e.sql_features,
        )
        for e in sorted(entries, key=lambda e: e.id)
    ]


@router.get("/{query_id}")
async def get_query(query_id: str) -> QueryDefinition:
    """Full entry, SQL text and variants included."""
    catalog = get_catalog()
    if query_id not in catalog:
        raise HTTPException(
            status_code=404, detail=f"Unknown catalog query id: {query_id}"
        )
    return catalog[query_id]

"""Shared pytest fixtures.

CLAUDE.md's "Перевіряй, а не припускай" extends to the test suite itself:
these fixtures talk to a real PostgreSQL server through the same
saw_readonly pool app.db.Pools builds in production, rather than mocking
psycopg — a mock would only prove the tests agree with themselves, not
that the SQL and the READ ONLY / statement_timeout wiring actually work.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.catalog import DEFAULT_CATALOG_ROOT, load_catalog
from app.config import get_settings
from app.models import QueryDefinition


@pytest_asyncio.fixture()
async def readonly_pool() -> AsyncIterator[AsyncConnectionPool]:
    """The museum saw_readonly pool — every catalog entry currently
    targets museum (dvdrental's catalog is still empty; see TODO.md).

    Function-scoped deliberately: a session-scoped async pool needs a
    session-scoped event loop too, and overriding pytest-asyncio's
    event_loop fixture for that (the standard pre-1.0 workaround) hung
    indefinitely here under pytest-asyncio 0.24 with anyio also
    installed (a transitive dependency of httpx) — both register a
    "mode=auto" asyncio plugin, and mixing that with a custom
    session-scoped loop is exactly the combination pytest-asyncio's own
    docs warn produces silent deadlocks. A fresh pool per test costs one
    extra connection handshake (tens of ms) — trivial next to actually
    hanging the suite.
    """
    settings = get_settings()
    pool = AsyncConnectionPool(
        conninfo=settings.conninfo(settings.museum_db, "readonly"),
        min_size=1,
        max_size=5,
        kwargs={"row_factory": dict_row, "autocommit": True},
        open=False,
    )
    await pool.open()
    yield pool
    await pool.close()


@pytest.fixture(scope="session")
def catalog() -> dict[str, QueryDefinition]:
    """Loaded straight from disk, not app.catalog.get_catalog()'s
    lru_cache — this always reflects whatever queries/ contains right
    now, the same as a fresh app start would see."""
    return load_catalog(DEFAULT_CATALOG_ROOT)

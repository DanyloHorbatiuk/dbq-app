"""Application entrypoint: builds the FastAPI app, opens/closes the
connection pools around the app's lifetime, and serves the static
frontend. Run via `uvicorn app.main:app` (see docker-compose.yml).
"""

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.catalog import CatalogError, get_catalog
from app.config import get_settings
from app.db import Pools
from app.routers.catalog import router as catalog_router
from app.routers.meta import router as meta_router

# Loaded eagerly at import time, before the FastAPI app object even
# exists — not inside lifespan. A bad catalog is a startup-time
# configuration error, not a request-time one, and ROADMAP.md's own
# Etap 5 check requires a clean one-line message with a non-zero exit
# code, not a traceback: importing (and therefore validating) the
# catalog here, outside any async/exception-handling machinery FastAPI
# or uvicorn would otherwise wrap it in, is what makes that possible.
try:
    get_catalog()
except CatalogError as exc:
    print(f"FATAL: query catalog failed to load: {exc}", file=sys.stderr)
    sys.exit(1)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    pools = Pools(settings)
    await pools.open_all()
    app.state.pools = pools
    try:
        yield
    finally:
        await pools.close_all()


app = FastAPI(
    title="SQL Analytics Workbench",
    description="Навчально-дослідницький застосунок для аналітичних SQL-запитів.",
    lifespan=lifespan,
)

app.include_router(meta_router, prefix="/api")
app.include_router(catalog_router, prefix="/api")

# Mounted last and at "/": API routes registered above always match
# first, so this only ever serves the frontend's static files (added in
# Etap 11) instead of shadowing /api/*.
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")

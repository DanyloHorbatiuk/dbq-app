"""Application entrypoint: builds the FastAPI app, opens/closes the
connection pools around the app's lifetime, and serves the static
frontend. Run via `uvicorn app.main:app` (see docker-compose.yml).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.db import Pools
from app.routers.meta import router as meta_router


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

# Mounted last and at "/": API routes registered above always match
# first, so this only ever serves the frontend's static files (added in
# Etap 11) instead of shadowing /api/*.
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")

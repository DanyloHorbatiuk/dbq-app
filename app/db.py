"""Connection pooling: two independent pools per database (admin,
readonly), per SPEC.md §4.1. The admin pool is never used to run
user-submitted SQL — only for schema-owning operations added in later
stages (index experiments, REFRESH MATERIALIZED VIEW). Every connection
uses dict_row so query results are JSON-ready dicts without a manual
conversion step in every router.
"""

from typing import Literal

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import Role, Settings

Database = Literal["museum", "dvdrental"]

_DATABASES: tuple[Database, ...] = ("museum", "dvdrental")
_ROLES: tuple[Role, ...] = ("admin", "readonly")


class Pools:
    """Holds one AsyncConnectionPool per (database, role) pair (4 total)."""

    def __init__(self, settings: Settings) -> None:
        self._pools: dict[tuple[Database, Role], AsyncConnectionPool] = {}
        for database in _DATABASES:
            db_name = (
                settings.museum_db if database == "museum" else settings.dvdrental_db
            )
            for role in _ROLES:
                self._pools[(database, role)] = AsyncConnectionPool(
                    conninfo=settings.conninfo(db_name, role),
                    min_size=1,
                    max_size=5,
                    # autocommit=True: connections sit idle in the pool
                    # between requests, and an open (non-autocommit)
                    # transaction left dangling on a reused connection is
                    # exactly the kind of bug pooling is prone to. The
                    # executor (Etap 6) still gets its required
                    # BEGIN READ ONLY per SPEC.md §ФВ-02 explicitly, via
                    # `async with conn.transaction():` — autocommit mode
                    # doesn't prevent opening one, it just stops one from
                    # being left open by accident.
                    kwargs={"row_factory": dict_row, "autocommit": True},
                    open=False,
                )

    async def open_all(self) -> None:
        for pool in self._pools.values():
            await pool.open()

    async def close_all(self) -> None:
        for pool in self._pools.values():
            await pool.close()

    def get(self, database: Database, role: Role) -> AsyncConnectionPool:
        return self._pools[(database, role)]

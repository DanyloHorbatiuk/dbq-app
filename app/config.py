"""Application configuration, read entirely from the environment.

CLAUDE.md forbids secrets in source: docker-compose.yml injects every
value used here from .env, so a missing required variable fails fast at
startup instead of silently falling back to something insecure.
pydantic-settings matches field names to environment variables
case-insensitively by default, so `museum_db` below reads MUSEUM_DB
without needing an explicit alias.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings

Role = Literal["admin", "readonly"]


class Settings(BaseSettings):
    # PGHOST/PGPORT (no underscore) follow libpq's own env var convention,
    # which docker-compose.yml uses — pydantic-settings' default
    # case-insensitive matching would otherwise look for PG_HOST/PG_PORT.
    pg_host: str = Field(default="postgres", validation_alias="PGHOST")
    pg_port: int = Field(default=5432, validation_alias="PGPORT")

    museum_db: str
    dvdrental_db: str

    saw_admin_user: str
    saw_admin_password: str
    saw_readonly_user: str
    saw_readonly_password: str

    statement_timeout_ms: int = 15000
    default_row_limit: int = 1000
    benchmark_default_runs: int = 10
    log_level: str = "info"

    def conninfo(self, db_name: str, role: Role) -> str:
        """Build a libpq connection string for a (database, role) pair.

        role is "admin" (saw_admin, schema owner — index experiments and
        REFRESH MATERIALIZED VIEW only) or "readonly" (saw_readonly,
        SELECT-only — every catalog query and every piece of arbitrary
        user SQL). Never used for museum_manager: that role is for a
        human via pgAdmin, not the API (SPEC.md §4.1).
        """
        user, password = (
            (self.saw_admin_user, self.saw_admin_password)
            if role == "admin"
            else (self.saw_readonly_user, self.saw_readonly_password)
        )
        return (
            f"host={self.pg_host} port={self.pg_port} dbname={db_name} "
            f"user={user} password={password}"
        )


@lru_cache
def get_settings() -> Settings:
    """Cached so pydantic-settings only reads the environment once."""
    return Settings()

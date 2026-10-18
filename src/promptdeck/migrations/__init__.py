"""Schema migrations. ``upgrade(engine)`` uses Alembic when installed, else ``create_all``."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine
from sqlalchemy.ext.asyncio import AsyncEngine

from ..schema import DEFAULT_PREFIX, build_tables

log = logging.getLogger("promptdeck")
HERE = Path(__file__).parent


def _alembic_config(prefix: str, connection: Connection) -> Any:
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(HERE))
    cfg.set_main_option("version_table", f"{prefix}alembic_version")
    cfg.attributes["connection"] = connection
    cfg.attributes["prefix"] = prefix
    return cfg


def upgrade_sync(connection: Connection, prefix: str = DEFAULT_PREFIX, revision: str = "head") -> str:
    """Run migrations on an open sync connection. Returns ``alembic`` or ``create_all``."""
    try:
        from alembic import command
    except ImportError:
        log.warning(
            "alembic is not installed; creating tables with create_all "
            "(install promptdeck[alembic] for versioned migrations)"
        )
        build_tables(prefix).metadata.create_all(connection)
        return "create_all"
    command.upgrade(_alembic_config(prefix, connection), revision)
    return "alembic"


def upgrade(engine: Engine | AsyncEngine, prefix: str = DEFAULT_PREFIX, revision: str = "head") -> str:
    """Migrate the schema to ``revision`` with a sync or async engine."""
    if isinstance(engine, AsyncEngine):

        async def go() -> str:
            async with engine.begin() as conn:
                return await conn.run_sync(upgrade_sync, prefix, revision)

        return asyncio.run(go())
    with engine.begin() as conn:
        return upgrade_sync(conn, prefix, revision)


async def aupgrade(engine: AsyncEngine, prefix: str = DEFAULT_PREFIX, revision: str = "head") -> str:
    async with engine.begin() as conn:
        return await conn.run_sync(upgrade_sync, prefix, revision)

"""Fixtures. SQLite runs everywhere; set PROMPTREGISTRY_TEST_POSTGRES_URL / PROMPTREGISTRY_TEST_MYSQL_URL to
run the same suite against real servers (CI does)."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool, StaticPool

from promptregistry import PromptRegistry

SYNC_URLS = {"sqlite": "sqlite://"}
ASYNC_URLS = {"sqlite": "sqlite+aiosqlite://"}
if os.environ.get("PROMPTREGISTRY_TEST_POSTGRES_URL"):
    SYNC_URLS["postgres"] = os.environ["PROMPTREGISTRY_TEST_POSTGRES_URL"]
    ASYNC_URLS["postgres"] = SYNC_URLS["postgres"].replace("postgresql+psycopg://", "postgresql+asyncpg://")
if os.environ.get("PROMPTREGISTRY_TEST_MYSQL_URL"):
    SYNC_URLS["mysql"] = os.environ["PROMPTREGISTRY_TEST_MYSQL_URL"]
    ASYNC_URLS["mysql"] = SYNC_URLS["mysql"].replace("mysql+pymysql://", "mysql+aiomysql://")


def _prefix() -> str:
    return f"pd_{uuid.uuid4().hex[:8]}_"


@pytest.fixture(params=list(SYNC_URLS))
def registry(request: pytest.FixtureRequest) -> Iterator[PromptRegistry]:
    url = SYNC_URLS[request.param]
    kw = {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}} if url == "sqlite://" else {}
    engine = create_engine(url, **kw)
    reg = PromptRegistry(engine, table_prefix=_prefix(), cache_ttl=30)
    reg.create_tables()
    yield reg
    reg.tables.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(params=list(ASYNC_URLS))
async def aregistry(request: pytest.FixtureRequest) -> AsyncIterator[PromptRegistry]:
    url = ASYNC_URLS[request.param]
    kw = {"poolclass": StaticPool} if "sqlite" in url else {"poolclass": NullPool}
    engine = create_async_engine(url, **kw)
    reg = PromptRegistry(engine, table_prefix=_prefix(), cache_ttl=30)
    await reg.acreate_tables()
    yield reg
    async with engine.begin() as conn:
        await conn.run_sync(reg.tables.metadata.drop_all)
    await engine.dispose()


def seed(reg: PromptRegistry) -> None:
    reg.create_prompt("support/agent", "text", actor="ann", tags=["support"], metadata={"owner": "cx"})
    reg.create_version(
        "support/agent",
        "Help {customer_name} on the {plan} plan.",
        format="python",
        message="init",
        actor="ann",
        config={"model": "m1", "temperature": 0.1},
    )
    reg.publish("support/agent", 1, "staging", actor="ann")
    reg.publish("support/agent", 1, "production", actor="ann", force=True, reason="seed")

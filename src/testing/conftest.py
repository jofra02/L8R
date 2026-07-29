"""Shared fixtures for the self-contained test suite.

`asset_engine` / `asset_session_factory` provide an in-memory sqlite schema
(PortableJSONB makes the asset tables sqlite-compatible; production DDL is
pure JSONB via alembic). Postgres-only behaviors (GIN containment filters,
partial unique indexes) are exercised in integration environments, not here.
"""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.core.database import Base
from src.core.orm import PlatformTenant  # noqa: F401 — ensures model import


@pytest.fixture()
async def asset_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def asset_session_factory(asset_engine):
    factory = async_sessionmaker(asset_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(PlatformTenant(customer_id="t1", name="Tenant One"))
        session.add(PlatformTenant(customer_id="t2", name="Tenant Two"))
        await session.commit()
    return factory

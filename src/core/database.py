from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from typing import AsyncGenerator
from src.config import settings

# Construct Async PG URL
# Ensure strict isolation and correct driver
DATABASE_URL = f"postgresql+asyncpg://{settings.DB_USER}:{settings.DB_PASS}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"

engine = create_async_engine(
    DATABASE_URL,
    echo=settings.LOG_LEVEL == "DEBUG",
    future=True,
    pool_pre_ping=True
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting async session."""
    async with async_session_factory() as session:
        yield session

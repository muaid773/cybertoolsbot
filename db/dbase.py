# database.py

from collections.abc import AsyncGenerator
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from config import DB_URL

def build_async_database_url(url: str) -> str:
    """Convert database URL to async SQLAlchemy URL."""

    if not url:
        raise RuntimeError("DB_URL is required.")

    # SQLite
    if url.startswith("sqlite:///"):
        return url.replace(
            "sqlite:///",
            "sqlite+aiosqlite:///",
            1,
        )

    # postgres:// -> postgresql://
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]

    parsed = urlparse(url)

    # PostgreSQL
    if parsed.scheme in ("postgresql", "postgres"):
        parsed = parsed._replace(
            scheme="postgresql+asyncpg"
        )

        query = [
            (k, v)
            for k, v in parse_qsl(
                parsed.query,
                keep_blank_values=True
            )
            if k != "sslmode"
        ]

        parsed = parsed._replace(
            query=urlencode(query)
        )

        return urlunparse(parsed)

    if parsed.scheme == "postgresql+asyncpg":
        return url

    raise RuntimeError(f"Unsupported database URL: {url}")


DATABASE_URL = build_async_database_url(DB_URL)

connect_args = {}

if DATABASE_URL.startswith("sqlite"):
    connect_args = {
        "check_same_thread": False
    }

elif DATABASE_URL.startswith("postgresql+asyncpg"):
    connect_args = {
        "ssl": True
    }

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    connect_args={
        "ssl": "require"
    }
)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
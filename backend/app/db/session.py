from collections.abc import AsyncGenerator
import os
import ssl
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.config import settings


def clean_database_url(url: str) -> str:
    if not url:
        return "sqlite+aiosqlite:///:memory:"

    # SQLite URLs have empty netloc, which urlunparse mangles (/// -> :/)
    if url.startswith("sqlite"):
        return url

    # 1. Ensure asyncpg dialect for Postgres
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    # 2. Parse URL and remove libpq-only parameters that break asyncpg
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)

    unsupported_keys = ["sslmode", "channel_binding", "target_session_attrs"]
    for key in unsupported_keys:
        query_params.pop(key, None)

    new_query = urlencode(query_params, doseq=True)
    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        new_query,
        parsed.fragment,
    ))


raw_db_url = (settings.DATABASE_URL or os.getenv("DATABASE_URL") or "").strip()
cleaned_url = clean_database_url(raw_db_url)

connect_args = {}
if cleaned_url.startswith("postgresql+asyncpg://"):
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    connect_args = {"ssl": ssl_context}

engine = create_async_engine(
    cleaned_url,
    echo=False,
    pool_pre_ping=True,
    connect_args=connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
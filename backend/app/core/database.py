from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

from app.core.config import settings

# A hosted Postgres closes idle connections on its own schedule; without a
# ping the first request after a quiet spell fails on a dead socket.
_engine_options = (
    {} if settings.DATABASE_URL.startswith("sqlite") else {"pool_pre_ping": True}
)

engine = create_async_engine(
    settings.DATABASE_URL, echo=settings.SQL_ECHO, **_engine_options
)
AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

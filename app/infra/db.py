"""异步数据库引擎与会话工厂。"""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.conf.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def dispose_engine() -> None:
    await engine.dispose()

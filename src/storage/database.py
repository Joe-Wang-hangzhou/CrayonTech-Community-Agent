from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .models import Base, DailySummary, GroupMessage

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str) -> None:
    """初始化全局数据库引擎和会话工厂。只调用一次。"""
    global _engine, _session_factory
    _engine = create_async_engine(database_url, echo=False, pool_pre_ping=True)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def create_tables() -> None:
    """在数据库中创建所有缺失的表（不使用迁移框架）。"""
    if _engine is None:
        raise RuntimeError("数据库引擎未初始化，请先调用 init_engine()")
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def get_session() -> AsyncSession:
    """获取一个新的异步会话。调用方负责 async with 或手动 close。"""
    if _session_factory is None:
        raise RuntimeError("数据库引擎未初始化，请先调用 init_engine()")
    return _session_factory()


async def close_engine() -> None:
    """关闭数据库引擎连接池。"""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None

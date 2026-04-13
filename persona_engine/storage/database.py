"""
数据库模块

SQLite 数据库初始化和连接管理
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import text, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from ..core.config import config
from ..core.exceptions import DatabaseError


logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """SQLAlchemy ORM 基类"""
    pass


class Database:
    """
    数据库管理器

    使用 SQLAlchemy 2.0 + asyncio + SQLite
    """

    _instance: "Database | None" = None
    _engine = None
    _session_factory: async_sessionmaker[AsyncSession] | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._engine is None:
            self._initialize()

    def _initialize(self) -> None:
        """初始化数据库引擎"""
        db_config = config.database

        # 使用 aiosqlite 驱动
        db_path = Path(db_config.path)
        if not db_path.is_absolute():
            db_path = Path(__file__).parent.parent / db_config.path

        # 确保目录存在
        db_path.parent.mkdir(parents=True, exist_ok=True)

        database_url = f"sqlite+aiosqlite:///{db_path}"

        # 使用 NullPool 替代 StaticPool，让 aiosqlite 自行管理连接池
        # 这样每次连接时都会执行 PRAGMA 设置（WAL 模式在每个新连接上都需要设置）
        self._engine = create_async_engine(
            database_url,
            echo=db_config.echo,
            pool_pre_ping=True,
            connect_args={
                "timeout": 30,  # 等待 30 秒而不是立刻抛出 database is locked
            },
            poolclass=NullPool,
        )

        # 强制开启 WAL 模式 (Write-Ahead Logging) 以支持并发读写
        # NullPool 每次获取连接都会触发 connect 事件
        @event.listens_for(self._engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        logger.info(f"Database initialized: {db_path} (WAL mode enabled)")

    @property
    def engine(self):
        """获取引擎"""
        if self._engine is None:
            self._initialize()
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """获取会话工厂"""
        if self._session_factory is None:
            self._initialize()
        return self._session_factory

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        获取数据库会话的上下文管理器

        用法：
        async with db.session() as session:
            result = await session.execute(...)
        """
        if self._session_factory is None:
            self._initialize()

        session = self._session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            try:
                await session.close()
            except Exception as e:
                logger.warning(f"Session close failed: {e}")

    async def create_tables(self) -> None:
        """创建所有表 (使用 SQLAlchemy 自动化管理)

        使用 Base.metadata.create_all 自动根据模型定义创建表，
        确保模型与表结构完全一致，避免手动写 SQL 导致的维护割裂问题。
        """
        try:
            # 使用 async engine 运行同步的 create_all
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tables created via SQLAlchemy metadata")
        except Exception as e:
            raise DatabaseError(
                message=f"Failed to create tables: {str(e)}",
                operation="create_tables",
            )

    async def drop_tables(self) -> None:
        """删除所有表（慎用）"""
        try:
            async with self._engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
            logger.warning("Database tables dropped")
        except Exception as e:
            raise DatabaseError(
                message=f"Failed to drop tables: {str(e)}",
                operation="drop_tables",
            )

    async def health_check(self) -> bool:
        """数据库健康检查"""
        try:
            async with self.session() as session:
                await session.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False

    async def close(self) -> None:
        """关闭数据库连接"""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            logger.info("Database connection closed")


# 全局数据库实例
database = Database()


# ========== SQLAlchemy 模型定义 ==========

from datetime import datetime
from sqlalchemy import Column, String, Text, Float, Integer, DateTime, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column


class PersonaModel(Base):
    """人格画像表"""
    __tablename__ = "personas"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    verbal_tics: Mapped[list] = mapped_column(JSON, default=list)
    grammar_prefs: Mapped[list] = mapped_column(JSON, default=list)
    logic_architecture: Mapped[dict] = mapped_column(JSON, default=dict)
    temporal_patterns: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)
    source_asr_texts: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )


class RewriteTaskModel(Base):
    """重写任务表"""
    __tablename__ = "rewrite_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    persona_ids: Mapped[list] = mapped_column(JSON, default=list)
    locked_terms: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    best_text: Mapped[str] = mapped_column(Text, default="")
    best_score: Mapped[float] = mapped_column(Float, default=0.0)
    best_iteration: Mapped[int] = mapped_column(Integer, default=0)
    history_versions: Mapped[list] = mapped_column(JSON, default=list)
    intermediate_results: Mapped[list] = mapped_column(JSON, default=list)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class VideoProcessingTaskModel(Base):
    """视频处理任务表

    用于追踪人格创建过程中的视频 ASR 提取进度，支持断点续传。
    """
    __tablename__ = "video_processing_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    persona_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    video_urls: Mapped[list] = mapped_column(JSON, default=list)
    completed_urls: Mapped[list] = mapped_column(JSON, default=list)
    failed_urls: Mapped[list] = mapped_column(JSON, default=list)
    current_index: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(50), default="pending")  # pending/processing/completed/failed/cancelled
    asr_texts: Mapped[list] = mapped_column(JSON, default=list)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

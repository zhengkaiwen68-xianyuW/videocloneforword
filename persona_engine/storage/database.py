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
from sqlalchemy.pool import StaticPool

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

        self._engine = create_async_engine(
            database_url,
            echo=db_config.echo,
            pool_pre_ping=True,
            connect_args={
                "timeout": 30,  # 等待 30 秒而不是立刻抛出 database is locked
            },
            poolclass=StaticPool,
        )

        # 强制开启 WAL 模式 (Write-Ahead Logging) 以支持并发读写
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
            await session.close()

    async def create_tables(self) -> None:
        """创建所有表"""
        try:
            # 使用同步 sqlite3 直接创建表（避免 aiosqlite 在 Windows 上的问题）
            import sqlite3
            db_path = Path(config.database.path)
            if not db_path.is_absolute():
                db_path = Path(__file__).parent.parent / config.database.path

            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            # 创建 personas 表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS personas (
                    id VARCHAR(36) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    verbal_tics JSON NOT NULL DEFAULT '[]',
                    grammar_prefs JSON NOT NULL DEFAULT '[]',
                    logic_architecture JSON NOT NULL DEFAULT '{}',
                    temporal_patterns JSON NOT NULL DEFAULT '{}',
                    raw_json JSON NOT NULL DEFAULT '{}',
                    source_asr_texts JSON NOT NULL DEFAULT '[]',
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
            """)

            # 创建 rewrite_tasks 表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS rewrite_tasks (
                    id VARCHAR(36) PRIMARY KEY,
                    source_text TEXT NOT NULL,
                    persona_ids JSON NOT NULL DEFAULT '[]',
                    locked_terms JSON NOT NULL DEFAULT '[]',
                    status VARCHAR(50) NOT NULL DEFAULT 'pending',
                    best_text TEXT DEFAULT '',
                    best_score FLOAT NOT NULL DEFAULT 0.0,
                    best_iteration INTEGER NOT NULL DEFAULT 0,
                    history_versions JSON NOT NULL DEFAULT '[]',
                    intermediate_results JSON NOT NULL DEFAULT '[]',
                    error_message TEXT,
                    created_at DATETIME NOT NULL,
                    completed_at DATETIME
                )
            """)

            conn.commit()
            conn.close()
            logger.info("Database tables created via sqlite3")
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

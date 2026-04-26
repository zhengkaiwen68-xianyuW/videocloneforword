"""
并发控制模块

基于 asyncio.Semaphore 的轻量并发限制器，控制：
- 视频处理任务并发数
- LLM API 调用并发数
- B站下载并发数
- API 请求限流

架构设计：
- 全局单例模式，与 config 联动
- Semaphore 限制同时运行的协程数
- 限流器使用滑动窗口计数
- 超限时返回 429 或排队等待
"""

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field

from .config import config

logger = logging.getLogger(__name__)


@dataclass
class RateLimitBucket:
    """滑动窗口限流桶"""
    timestamps: list[float] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class ConcurrencyLimiter:
    """
    全局并发限制器（单例）

    使用 Semaphore 控制并发数，使用滑动窗口实现 API 限流。
    """

    _instance: "ConcurrencyLimiter | None" = None

    def __new__(cls) -> "ConcurrencyLimiter":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        cfg = config.concurrency
        self._task_semaphore = asyncio.Semaphore(cfg.max_concurrent_tasks)
        self._llm_semaphore = asyncio.Semaphore(cfg.max_concurrent_llm)
        self._download_semaphore = asyncio.Semaphore(cfg.max_concurrent_downloads)
        self._rate_limit = cfg.api_rate_limit
        self._rate_window = cfg.api_rate_window
        self._queue_max_size = cfg.queue_max_size

        # 限流桶：per-IP 滑动窗口
        self._buckets: dict[str, RateLimitBucket] = defaultdict(RateLimitBucket)

        # 统计信息
        self._stats = {
            "tasks_acquired": 0,
            "tasks_rejected": 0,
            "llm_acquired": 0,
            "llm_queued": 0,
            "downloads_acquired": 0,
            "api_throttled": 0,
        }

        logger.info(
            f"ConcurrencyLimiter initialized: "
            f"tasks={cfg.max_concurrent_tasks}, "
            f"llm={cfg.max_concurrent_llm}, "
            f"downloads={cfg.max_concurrent_downloads}, "
            f"rate_limit={cfg.api_rate_limit}/{cfg.api_rate_window}s"
        )

    # ── 任务并发控制 ──

    async def acquire_task(self, task_id: str) -> bool:
        """
        获取任务槽位。如果已满，返回 False（调用方应返回 429）。

        Args:
            task_id: 任务 ID（用于日志）

        Returns:
            True 表示获取成功，False 表示已满
        """
        if self._task_semaphore._value == 0:
            self._stats["tasks_rejected"] += 1
            logger.warning(f"Task {task_id}: 并发任务已满，拒绝")
            return False

        await self._task_semaphore.acquire()
        self._stats["tasks_acquired"] += 1
        logger.info(
            f"Task {task_id}: 获取任务槽位 "
            f"(剩余 {self._task_semaphore._value}/{config.concurrency.max_concurrent_tasks})"
        )
        return True

    def release_task(self, task_id: str):
        """释放任务槽位"""
        self._task_semaphore.release()
        logger.info(
            f"Task {task_id}: 释放任务槽位 "
            f"(剩余 {self._task_semaphore._value}/{config.concurrency.max_concurrent_tasks})"
        )

    async def acquire_task_wait(self, task_id: str, timeout: float = 30.0) -> bool:
        """
        获取任务槽位，如果已满则等待（带超时）。

        用于需要排队的场景（如人格创建）。

        Args:
            task_id: 任务 ID
            timeout: 最大等待时间（秒）

        Returns:
            True 表示获取成功，False 表示超时
        """
        try:
            await asyncio.wait_for(
                self._task_semaphore.acquire(),
                timeout=timeout,
            )
            self._stats["tasks_acquired"] += 1
            logger.info(
                f"Task {task_id}: 排队后获取任务槽位 "
                f"(剩余 {self._task_semaphore._value})"
            )
            return True
        except asyncio.TimeoutError:
            self._stats["tasks_rejected"] += 1
            logger.warning(f"Task {task_id}: 等待任务槽位超时 ({timeout}s)")
            return False

    # ── LLM 并发控制 ──

    async def acquire_llm(self, caller: str = "") -> bool:
        """
        获取 LLM 调用槽位。阻塞等待直到有空位。

        Args:
            caller: 调用方标识（用于日志）
        """
        self._stats["llm_queued"] += 1
        await self._llm_semaphore.acquire()
        self._stats["llm_acquired"] += 1
        logger.debug(
            f"LLM 槽位获取: {caller} "
            f"(剩余 {self._llm_semaphore._value}/{config.concurrency.max_concurrent_llm})"
        )
        return True

    def release_llm(self, caller: str = ""):
        """释放 LLM 调用槽位"""
        self._llm_semaphore.release()
        logger.debug(
            f"LLM 槽位释放: {caller} "
            f"(剩余 {self._llm_semaphore._value}/{config.concurrency.max_concurrent_llm})"
        )

    # ── 下载并发控制 ──

    async def acquire_download(self, url: str = "") -> bool:
        """获取下载槽位"""
        await self._download_semaphore.acquire()
        self._stats["downloads_acquired"] += 1
        logger.debug(
            f"下载槽位获取: {url[:50]} "
            f"(剩余 {self._download_semaphore._value})"
        )
        return True

    def release_download(self, url: str = ""):
        """释放下载槽位"""
        self._download_semaphore.release()

    # ── API 限流 ──

    async def check_rate_limit(self, client_ip: str) -> bool:
        """
        检查 API 限流（滑动窗口）。

        Args:
            client_ip: 客户端 IP

        Returns:
            True 表示允许，False 表示被限流
        """
        bucket = self._buckets[client_ip]
        now = time.monotonic()

        async with bucket.lock:
            # 清理过期的时间戳
            cutoff = now - self._rate_window
            bucket.timestamps = [ts for ts in bucket.timestamps if ts > cutoff]

            if len(bucket.timestamps) >= self._rate_limit:
                self._stats["api_throttled"] += 1
                logger.warning(f"API 限流: {client_ip} ({len(bucket.timestamps)}/{self._rate_limit})")
                return False

            bucket.timestamps.append(now)
            return True

    # ── 状态查询 ──

    def get_status(self) -> dict:
        """获取并发控制状态"""
        cfg = config.concurrency
        return {
            "tasks": {
                "max": cfg.max_concurrent_tasks,
                "available": self._task_semaphore._value,
                "in_use": cfg.max_concurrent_tasks - self._task_semaphore._value,
            },
            "llm": {
                "max": cfg.max_concurrent_llm,
                "available": self._llm_semaphore._value,
                "in_use": cfg.max_concurrent_llm - self._llm_semaphore._value,
            },
            "downloads": {
                "max": cfg.max_concurrent_downloads,
                "available": self._download_semaphore._value,
                "in_use": cfg.max_concurrent_downloads - self._download_semaphore._value,
            },
            "stats": self._stats.copy(),
        }


# 全局单例
concurrency_limiter = ConcurrencyLimiter()

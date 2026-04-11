"""
任务注册表 - 用于追踪后台任务并在shutdown时取消

避免循环导入：main.py 和 routes.py 都导入此模块
"""
import asyncio
import logging
from typing import Dict

logger = logging.getLogger(__name__)


class TaskRegistry:
    """全局任务注册表"""

    def __init__(self):
        self._tasks: Dict[str, asyncio.Task] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                self._loop = asyncio.get_event_loop()
        return self._loop

    def register(self, task_id: str, task: asyncio.Task):
        """注册一个新任务"""
        self._tasks[task_id] = task
        logger.info(f"Task registered: {task_id} (total: {len(self._tasks)})")

    def unregister(self, task_id: str):
        """任务完成后移除"""
        if task_id in self._tasks:
            del self._tasks[task_id]
            logger.info(f"Task unregistered: {task_id} (remaining: {len(self._tasks)})")

    def get(self, task_id: str) -> asyncio.Task | None:
        """获取任务引用"""
        return self._tasks.get(task_id)

    def cancel(self, task_id: str) -> bool:
        """取消指定任务"""
        task = self._tasks.get(task_id)
        if task is None:
            return False
        if not task.done():
            task.cancel()
            logger.info(f"Task cancelled: {task_id}")
            return True
        return False

    def cancel_all(self):
        """取消所有任务（shutdown时调用）"""
        logger.info(f"Cancelling {len(self._tasks)} background tasks...")
        for task_id, task in list(self._tasks.items()):
            if not task.done():
                task.cancel()
                logger.info(f"Task cancelled: {task_id}")
        self._tasks.clear()

    async def wait_all(self, timeout: float = 5.0):
        """等待所有任务完成（带超时）"""
        if not self._tasks:
            return
        pending = [t for t in self._tasks.values() if not t.done()]
        if not pending:
            return
        logger.info(f"Waiting for {len(pending)} tasks to complete...")
        done, pending = await asyncio.wait(pending, timeout=timeout)
        for task in pending:
            task.cancel()
        self._tasks.clear()

    def list_tasks(self) -> list[str]:
        """列出所有任务ID"""
        return list(self._tasks.keys())


# 全局单例
task_registry = TaskRegistry()
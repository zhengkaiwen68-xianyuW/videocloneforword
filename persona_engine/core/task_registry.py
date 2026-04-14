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
        # 取消标志: {task_id: cancellation_generation}
        # 每次 cancel() 时递增，is_cancelled() 时校验 generation
        # 避免新任务重用相同 ID 时被旧任务的取消标志影响
        self._cancelled_generation: Dict[str, int] = {}
        self._task_generation: Dict[str, int] = {}  # 任务注册时的 generation

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
        # 为新任务分配新的 generation，每次注册递增
        # 取消状态通过 cancelled_generation != task_generation 来表示
        new_gen = self._task_generation.get(task_id, 0) + 1
        self._task_generation[task_id] = new_gen
        # 清除之前的取消状态——新任务不应被视为已取消
        self._cancelled_generation.pop(task_id, None)
        logger.info(f"Task registered: {task_id} (total: {len(self._tasks)})")

    def unregister(self, task_id: str):
        """任务完成后移除"""
        if task_id in self._tasks:
            del self._tasks[task_id]
        # 清除该任务的 generation 信息
        self._task_generation.pop(task_id, None)
        # 注意：不修改 _cancelled_generation，因为它可能被其他任务引用
        # 新任务注册时会通过 register() 重新建立正确的 generation 关系
        logger.info(f"Task unregistered: {task_id} (remaining: {len(self._tasks)})")

    def get(self, task_id: str) -> asyncio.Task | None:
        """获取任务引用"""
        return self._tasks.get(task_id)

    def cancel(self, task_id: str) -> bool:
        """取消指定任务

        直接调用 cancel() 而不先检查 done()，避免竞态条件。
        asyncio.Task.cancel() 对已完成的 task 是 no-op。
        设置 cancelled_generation = task_generation，使 is_cancelled() 返回 True。
        """
        task = self._tasks.get(task_id)
        if task is None:
            return False
        # 直接调用 cancel() - 它对已完成的任务是 no-op，不会抛异常
        # 这样避免在 if task.done() 和 task.cancel() 之间 task 被其他线程完成
        task.cancel()
        # 设置 cancelled_generation = task_generation，使 is_cancelled() 返回 True
        self._cancelled_generation[task_id] = self._task_generation[task_id]
        logger.info(f"Task cancellation requested: {task_id}")
        return True

    def is_cancelled(self, task_id: str) -> bool:
        """检查任务是否已被取消（通过 generation 匹配校验）

        只有当任务的 generation 与取消 generation 相同时才返回 True，
        避免新任务重用相同 ID 时被旧任务的取消标志影响。
        如果任务从未注册过，返回 False。
        """
        if task_id not in self._task_generation:
            return False  # 任务从未注册，不是 cancelled
        return self._cancelled_generation.get(task_id, 0) == self._task_generation.get(task_id, 0)

    def clear_cancelled_flag(self, task_id: str):
        """清除取消标志（任务完成后调用）"""
        # 递增 cancelled_generation，使其与 task_generation 不匹配
        # 这样 is_cancelled() 返回 False
        if task_id in self._cancelled_generation:
            self._cancelled_generation[task_id] += 1
        elif task_id in self._task_generation:
            # 如果之前没有取消记录，直接设置为 task_gen + 1
            self._cancelled_generation[task_id] = self._task_generation[task_id] + 1

    def cancel_all(self):
        """取消所有任务（shutdown时调用）"""
        logger.info(f"Cancelling {len(self._tasks)} background tasks...")
        for task_id, task in list(self._tasks.items()):
            task.cancel()  # 直接调用 cancel()，对已完成的任务是 no-op
            # 设置 cancelled_generation = task_generation，使 is_cancelled() 返回 True
            if task_id in self._task_generation:
                self._cancelled_generation[task_id] = self._task_generation[task_id]
            logger.info(f"Task cancellation requested: {task_id}")
        self._tasks.clear()
        # 保留 generations 以便追踪（但任务已清空）

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
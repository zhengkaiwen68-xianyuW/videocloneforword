"""
迭代控制器

管理重写迭代流程，实现熔断机制（5次/5分钟上限）
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from ..core.config import config
from ..core.exceptions import IterationTimeoutError
from ..core.types import TaskStatus, VersionEntry


logger = logging.getLogger(__name__)


@dataclass
class IterationState:
    """迭代状态"""
    task_id: str
    iteration: int = 0
    best_score: float = 0.0
    best_text: str = ""
    best_iteration: int = 0
    history: list[VersionEntry] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.now)
    last_updated_at: datetime = field(default_factory=datetime.now)
    status: TaskStatus = TaskStatus.PENDING


class IterationController:
    """
    迭代控制器

    功能：
    1. 控制重写迭代次数（默认最多 5 次）
    2. 控制全局超时（默认 5 分钟）
    3. 记录历史版本，保留最优解
    4. 达到阈值自动熔断

    使用方式：
    controller = IterationController(task_id="task_123")
    controller.start()

    for i in range(max_iterations):
        result = await rewrite_once(...)
        score = await controller.evaluate(result)

        if controller.should_stop(score):
            break
    """

    def __init__(
        self,
        task_id: str | None = None,
        max_iterations: int | None = None,
        timeout_seconds: int | None = None,
        min_score: float | None = None,
    ):
        """
        初始化迭代控制器

        Args:
            task_id: 任务 ID（自动生成）
            max_iterations: 最大迭代次数（默认 5）
            timeout_seconds: 超时时间秒数（默认 300 = 5分钟）
            min_score: 最低通过分数（默认 90）
        """
        self.task_id = task_id or str(uuid.uuid4())[:8]
        audit_config = config.audit

        self.max_iterations = max_iterations or audit_config.max_iterations
        self.timeout_seconds = timeout_seconds or audit_config.timeout_seconds
        self.min_score = min_score or audit_config.min_consistency_score

        self.state = IterationState(task_id=self.task_id)
        self._start_time: float | None = None

    def start(self) -> None:
        """开始迭代计时"""
        self._start_time = time.time()
        self.state.status = TaskStatus.RUNNING
        logger.info(f"Task {self.task_id} started: max_iterations={self.max_iterations}, timeout={self.timeout_seconds}s")

    def start_if_not_started(self) -> None:
        """如果未开始则开始"""
        if self._start_time is None:
            self.start()

    @property
    def elapsed_seconds(self) -> float:
        """已用时间（秒）"""
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time

    @property
    def remaining_seconds(self) -> float:
        """剩余时间（秒）"""
        return max(0, self.timeout_seconds - self.elapsed_seconds)

    @property
    def iteration_count(self) -> int:
        """当前迭代次数"""
        return self.state.iteration

    def should_continue(self) -> bool:
        """
        判断是否应该继续迭代

        终止条件：
        1. 已达到最大迭代次数
        2. 已超时
        3. 上一次得分已达标

        Returns:
            True 继续，False 停止
        """
        # 检查是否超时
        if self.elapsed_seconds >= self.timeout_seconds:
            logger.warning(
                f"Task {self.task_id} timeout: {self.elapsed_seconds:.1f}s >= {self.timeout_seconds}s"
            )
            self.state.status = TaskStatus.TIMEOUT
            return False

        # 检查迭代次数
        if self.state.iteration >= self.max_iterations:
            logger.info(
                f"Task {self.task_id} reached max iterations: {self.state.iteration}/{self.max_iterations}"
            )
            return False

        # 如果已达标，不再继续
        if self.state.best_score >= self.min_score:
            logger.info(
                f"Task {self.task_id} already passed: {self.state.best_score:.2f} >= {self.min_score}"
            )
            return False

        return True

    def should_stop(self, score: float) -> bool:
        """
        判断是否应该停止

        Args:
            score: 当前得分

        Returns:
            True 停止，False 继续
        """
        return not self.should_continue()

    async def evaluate_and_record(
        self,
        rewritten_text: str,
        score: float,
        metadata: dict | None = None,
    ) -> dict[str, Any]:
        """
        评估当前迭代并记录

        Args:
            rewritten_text: 重写文本
            score: 一致性评分
            metadata: 额外元数据

        Returns:
            评估结果 {
                "should_continue": bool,
                "is_new_best": bool,
                "best_score": float,
                "best_text": str,
                "iteration": int
            }
        """
        self.state.iteration += 1
        self.state.last_updated_at = datetime.now()

        # 记录版本
        version = VersionEntry(
            version=len(self.state.history) + 1,
            text=rewritten_text,
            consistency_score=score,
            iteration=self.state.iteration,
        )
        self.state.history.append(version)

        # 检查是否是最优
        is_new_best = False
        if score > self.state.best_score:
            self.state.best_score = score
            self.state.best_text = rewritten_text
            self.state.best_iteration = self.state.iteration
            is_new_best = True
            logger.info(
                f"Task {self.task_id} new best score: {score:.2f} at iteration {self.state.iteration}"
            )

        # 判断是否继续
        should_continue = self.should_continue()

        return {
            "should_continue": should_continue,
            "is_new_best": is_new_best,
            "best_score": self.state.best_score,
            "best_text": self.state.best_text,
            "best_iteration": self.state.best_iteration,
            "iteration": self.state.iteration,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "remaining_seconds": round(self.remaining_seconds, 1),
            "score": score,
            "passed": score >= self.min_score,
            "status": self.state.status.value,
        }

    def get_best_result(
        self,
        final_text: str | None = None,
        final_score: float | None = None,
    ) -> dict[str, Any]:
        """
        获取最佳结果

        如果最终得分未达标，返回历史最优。

        Args:
            final_text: 最终文本（当前迭代结果）
            final_score: 最终得分

        Returns:
            最终结果字典
        """
        # 如果最终结果达标，使用最终结果
        if final_score is not None and final_score >= self.min_score:
            self.state.status = TaskStatus.COMPLETED
            return {
                "text": final_text,
                "score": final_score,
                "is_final": True,
                "iteration": self.state.iteration,
                "best_score": self.state.best_score,
                "best_iteration": self.state.best_iteration,
            }

        # 否则使用历史最优
        self.state.status = TaskStatus.COMPLETED
        return {
            "text": self.state.best_text,
            "score": self.state.best_score,
            "is_final": False,
            "iteration": self.state.best_iteration,
            "fallback_reason": "final score below threshold, using best historical result",
            "best_score": self.state.best_score,
            "best_iteration": self.state.best_iteration,
        }

    def get_status(self) -> dict[str, Any]:
        """
        获取当前状态

        Returns:
            状态字典
        """
        return {
            "task_id": self.task_id,
            "status": self.state.status.value,
            "iteration": self.state.iteration,
            "max_iterations": self.max_iterations,
            "best_score": self.state.best_score,
            "best_iteration": self.state.best_iteration,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "remaining_seconds": round(self.remaining_seconds, 1),
            "timeout_seconds": self.timeout_seconds,
            "min_score": self.min_score,
            "history_count": len(self.state.history),
        }

    def check_timeout(self) -> bool:
        """
        检查是否超时

        Returns:
            True 超时，False 未超时
        """
        if self.elapsed_seconds >= self.timeout_seconds:
            self.state.status = TaskStatus.TIMEOUT
            return True
        return False

    async def run_with_rewrite(
        self,
        rewrite_func: Callable,  # 异步重写函数
        *args,
        **kwargs,
    ) -> dict[str, Any]:
        """
        运行带迭代的重写流程

        Args:
            rewrite_func: 异步重写函数，签名为 async def func(iteration: int) -> tuple[str, float]
            *args, **kwargs: 传递给 rewrite_func 的额外参数

        Returns:
            最终结果

        Raises:
            IterationTimeoutError: 超时
        """
        self.start()

        while self.should_continue():
            try:
                # 调用重写函数
                result = await rewrite_func(iteration=self.state.iteration + 1, *args, **kwargs)
                rewritten_text, score = result[0], result[1]

                # 评估并记录
                eval_result = await self.evaluate_and_record(rewritten_text, score)

                # 如果达标，结束
                if eval_result["passed"]:
                    break

                # 如果是最后一次迭代，也结束
                if self.state.iteration >= self.max_iterations:
                    break

            except Exception as e:
                logger.error(f"Task {self.task_id} iteration error: {e}")
                self.state.history.append(
                    VersionEntry(
                        version=len(self.state.history) + 1,
                        text="",
                        consistency_score=0,
                        iteration=self.state.iteration + 1,
                    )
                )
                break

        # 检查超时
        if self.check_timeout():
            raise IterationTimeoutError(
                message=f"Task {self.task_id} iteration timeout",
                iteration=self.state.iteration,
                elapsed_seconds=self.elapsed_seconds,
                max_iterations=self.max_iterations,
                timeout_seconds=self.timeout_seconds,
            )

        return self.get_best_result()


class BatchIterationController:
    """
    批量迭代控制器

    管理多个任务的并行迭代
    """

    def __init__(
        self,
        max_iterations: int | None = None,
        timeout_seconds: int | None = None,
        min_score: float | None = None,
    ):
        """
        初始化批量控制器

        Args:
            max_iterations: 最大迭代次数
            timeout_seconds: 超时时间
            min_score: 最低通过分数
        """
        self.max_iterations = max_iterations
        self.timeout_seconds = timeout_seconds
        self.min_score = min_score
        self.controllers: dict[str, IterationController] = {}

    def create_task(self, task_id: str) -> IterationController:
        """为新任务创建控制器"""
        controller = IterationController(
            task_id=task_id,
            max_iterations=self.max_iterations,
            timeout_seconds=self.timeout_seconds,
            min_score=self.min_score,
        )
        self.controllers[task_id] = controller
        return controller

    def get_controller(self, task_id: str) -> IterationController | None:
        """获取任务控制器"""
        return self.controllers.get(task_id)

    def get_all_status(self) -> list[dict[str, Any]]:
        """获取所有任务状态"""
        return [ctrl.get_status() for ctrl in self.controllers.values()]

    def cleanup_completed(self) -> int:
        """清理已完成的任务控制器"""
        completed = [
            tid for tid, ctrl in self.controllers.items()
            if ctrl.state.status in (TaskStatus.COMPLETED, TaskStatus.TIMEOUT)
        ]
        for tid in completed:
            del self.controllers[tid]
        return len(completed)

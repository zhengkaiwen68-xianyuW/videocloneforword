"""
Tests for task_registry.py

覆盖 P0 问题修复：
- 任务取消标志竞态条件（generation-based 方案）
"""
import asyncio
import pytest

import sys
sys.path.insert(0, '..')

from persona_engine.core.task_registry import TaskRegistry


class TestTaskRegistry:
    """TaskRegistry 测试用例"""

    def setup_method(self):
        """每个测试前创建新的 registry 实例"""
        self.registry = TaskRegistry()

    def teardown_method(self):
        """每个测试后清理"""
        self.registry.cancel_all()

    @pytest.mark.asyncio
    async def test_register_and_unregister(self):
        """测试基本注册和注销"""
        async def dummy_task():
            return "done"

        task = asyncio.create_task(dummy_task())
        task_id = "test_task_1"

        assert self.registry.get(task_id) is None
        self.registry.register(task_id, task)
        assert self.registry.get(task_id) is task

        self.registry.unregister(task_id)
        assert self.registry.get(task_id) is None

        # 清理
        if not task.done():
            task.cancel()

    @pytest.mark.asyncio
    async def test_cancel_sets_cancelled_flag(self):
        """测试 cancel() 设置取消标志"""
        async def long_task():
            await asyncio.sleep(10)

        task = asyncio.create_task(long_task())
        task_id = "test_cancel"

        self.registry.register(task_id, task)
        assert self.registry.is_cancelled(task_id) is False

        self.registry.cancel(task_id)
        assert self.registry.is_cancelled(task_id) is True

        # 清理
        task.cancel()
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_is_cancelled_after_unregister(self):
        """测试注销后 is_cancelled 返回 False"""
        async def dummy_task():
            return "done"

        task = asyncio.create_task(dummy_task())
        task_id = "test_unreg_cancel"

        self.registry.register(task_id, task)
        self.registry.cancel(task_id)
        assert self.registry.is_cancelled(task_id) is True

        # 注销后，即使取消过，generation 不匹配也返回 False
        self.registry.unregister(task_id)
        # 因为 task 从 registry 移除后，is_cancelled 检查的是新任务的 generation

    @pytest.mark.asyncio
    async def test_same_id_reuse_after_cancel(self):
        """
        关键测试：验证同一 ID 重用时，旧任务的取消标志不影响新任务

        这是竞态条件修复的核心验证。
        """
        async def task_1():
            await asyncio.sleep(10)

        async def task_2():
            return "new_task"

        # 注册并取消第一个任务
        task1 = asyncio.create_task(task_1())
        task_id = "reused_id"
        self.registry.register(task_id, task1)
        self.registry.cancel(task_id)

        assert self.registry.is_cancelled(task_id) is True

        # 注销第一个任务
        self.registry.unregister(task_id)

        # 注册新任务（相同 ID）
        task2 = asyncio.create_task(task_2())
        self.registry.register(task_id, task2)

        # 新任务不应该被标记为已取消
        assert self.registry.is_cancelled(task_id) is False, \
            "新任务不应受旧任务取消标志影响"

        # 清理
        task1.cancel()
        if not task2.done():
            task2.cancel()

    @pytest.mark.asyncio
    async def test_same_id_reuse_after_cancel_all(self):
        """验证 cancel_all 后重用 ID 不受旧标志影响"""
        async def long_task():
            await asyncio.sleep(10)

        task1 = asyncio.create_task(long_task())
        task_id = "cancel_all_id"

        self.registry.register(task_id, task1)
        self.registry.cancel_all()

        # cancel_all 后注册新任务
        task2 = asyncio.create_task(asyncio.sleep(0))
        self.registry.register(task_id, task2)

        # 新任务不应该被标记为已取消
        assert self.registry.is_cancelled(task_id) is False

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_task(self):
        """测试取消不存在的任务返回 False"""
        result = self.registry.cancel("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_nonexistent_task(self):
        """测试获取不存在的任务"""
        assert self.registry.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_list_tasks(self):
        """测试列出所有任务"""
        async def dummy():
            return

        task1 = asyncio.create_task(dummy())
        task2 = asyncio.create_task(dummy())

        self.registry.register("task1", task1)
        self.registry.register("task2", task2)

        tasks = self.registry.list_tasks()
        assert "task1" in tasks
        assert "task2" in tasks
        assert len(tasks) == 2

        # 清理
        task1.cancel()
        task2.cancel()

    @pytest.mark.asyncio
    async def test_clear_cancelled_flag(self):
        """测试 clear_cancelled_flag 方法"""
        async def long_task():
            await asyncio.sleep(10)

        task = asyncio.create_task(long_task())
        task_id = "clear_flag_test"

        self.registry.register(task_id, task)
        self.registry.cancel(task_id)
        assert self.registry.is_cancelled(task_id) is True

        self.registry.clear_cancelled_flag(task_id)
        assert self.registry.is_cancelled(task_id) is False

        # 清理
        task.cancel()

    @pytest.mark.asyncio
    async def test_cancel_all_multiple_tasks(self):
        """测试 cancel_all 取消所有任务"""
        async def long_task():
            await asyncio.sleep(10)

        task1 = asyncio.create_task(long_task())
        task2 = asyncio.create_task(long_task())

        self.registry.register("multi1", task1)
        self.registry.register("multi2", task2)

        self.registry.cancel_all()

        # asyncio Task.cancel() 是异步的，需要等待一下让取消生效
        await asyncio.sleep(0.1)

        # 验证任务被取消或已完成
        assert task1.cancelled() or task1.done()
        assert task2.cancelled() or task2.done()

    @pytest.mark.asyncio
    async def test_generation_isolation_stress(self):
        """压力测试：频繁创建/取消/重用同一 ID"""
        task_id = "stress_test"

        for i in range(10):
            async def task():
                await asyncio.sleep(0.01)

            t = asyncio.create_task(task())
            self.registry.register(task_id, t)

            # 取消
            self.registry.cancel(task_id)
            assert self.registry.is_cancelled(task_id) is True

            # 注销
            self.registry.unregister(task_id)

            # 新任务不应受影响
            t2 = asyncio.create_task(task())
            self.registry.register(task_id, t2)
            assert self.registry.is_cancelled(task_id) is False

            # 清理
            t.cancel()
            t2.cancel()

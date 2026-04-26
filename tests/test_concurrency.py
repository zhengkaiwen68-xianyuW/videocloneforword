"""
并发控制模块单元测试

测试 ConcurrencyLimiter 的核心逻辑：
- 任务槽位获取/释放
- LLM 槽位获取/释放
- 下载槽位获取/释放
- API 限流
- 状态查询
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock

from persona_engine.core.concurrency import ConcurrencyLimiter


# ── Fixtures ──

@pytest.fixture
def limiter():
    """创建一个新的 ConcurrencyLimiter 实例（重置单例）"""
    ConcurrencyLimiter._instance = None
    with patch("persona_engine.core.concurrency.config") as mock_config:
        mock_concurrency = MagicMock()
        mock_concurrency.max_concurrent_tasks = 2
        mock_concurrency.max_concurrent_llm = 3
        mock_concurrency.max_concurrent_downloads = 1
        mock_concurrency.api_rate_limit = 5
        mock_concurrency.api_rate_window = 60
        mock_concurrency.queue_max_size = 10
        mock_config.concurrency = mock_concurrency

        limiter = ConcurrencyLimiter()
        yield limiter

    ConcurrencyLimiter._instance = None


# ── Task Slot Tests ──

class TestTaskSlot:
    """任务槽位测试"""

    @pytest.mark.asyncio
    async def test_acquire_task_success(self, limiter):
        """正常获取任务槽位"""
        result = await limiter.acquire_task("task_1")
        assert result is True
        limiter.release_task("task_1")

    @pytest.mark.asyncio
    async def test_acquire_task_full(self, limiter):
        """任务槽位满时拒绝"""
        await limiter.acquire_task("task_1")
        await limiter.acquire_task("task_2")

        result = await limiter.acquire_task("task_3")
        assert result is False

        limiter.release_task("task_1")
        limiter.release_task("task_2")

    @pytest.mark.asyncio
    async def test_release_and_reacquire(self, limiter):
        """释放后可重新获取"""
        await limiter.acquire_task("task_1")
        await limiter.acquire_task("task_2")

        limiter.release_task("task_1")
        result = await limiter.acquire_task("task_3")
        assert result is True

        limiter.release_task("task_2")
        limiter.release_task("task_3")

    @pytest.mark.asyncio
    async def test_acquire_task_wait_success(self, limiter):
        """排队等待获取成功"""
        await limiter.acquire_task("task_1")

        # 启动一个延迟释放的协程
        async def delayed_release():
            await asyncio.sleep(0.1)
            limiter.release_task("task_1")

        asyncio.create_task(delayed_release())

        result = await limiter.acquire_task_wait("task_2", timeout=1.0)
        assert result is True
        limiter.release_task("task_2")

    @pytest.mark.asyncio
    async def test_acquire_task_wait_timeout(self, limiter):
        """排队等待超时"""
        await limiter.acquire_task("task_1")
        await limiter.acquire_task("task_2")

        result = await limiter.acquire_task_wait("task_3", timeout=0.1)
        assert result is False

        limiter.release_task("task_1")
        limiter.release_task("task_2")


# ── LLM Slot Tests ──

class TestLLMSlot:
    """LLM 槽位测试"""

    @pytest.mark.asyncio
    async def test_acquire_llm_success(self, limiter):
        """正常获取 LLM 槽位"""
        result = await limiter.acquire_llm("test_caller")
        assert result is True
        limiter.release_llm("test_caller")

    @pytest.mark.asyncio
    async def test_acquire_llm_concurrent(self, limiter):
        """多个 LLM 调用并发"""
        for i in range(3):
            await limiter.acquire_llm(f"caller_{i}")

        # 第4个应该阻塞
        async def try_acquire():
            return await limiter.acquire_llm("caller_3")

        # 用 wait_for 模拟超时
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(try_acquire(), timeout=0.1)

        for i in range(3):
            limiter.release_llm(f"caller_{i}")


# ── Download Slot Tests ──

class TestDownloadSlot:
    """下载槽位测试"""

    @pytest.mark.asyncio
    async def test_acquire_download_success(self, limiter):
        """正常获取下载槽位"""
        result = await limiter.acquire_download("http://test.com")
        assert result is True
        limiter.release_download("http://test.com")


# ── Rate Limit Tests ──

class TestRateLimit:
    """API 限流测试"""

    @pytest.mark.asyncio
    async def test_rate_limit_allow(self, limiter):
        """未超限时允许"""
        for _ in range(5):
            result = await limiter.check_rate_limit("192.168.1.1")
            assert result is True

    @pytest.mark.asyncio
    async def test_rate_limit_block(self, limiter):
        """超限时拒绝"""
        for _ in range(5):
            await limiter.check_rate_limit("192.168.1.2")

        result = await limiter.check_rate_limit("192.168.1.2")
        assert result is False

    @pytest.mark.asyncio
    async def test_rate_limit_different_ips(self, limiter):
        """不同 IP 独立计数"""
        for _ in range(5):
            await limiter.check_rate_limit("10.0.0.1")

        # 不同 IP 不受影响
        result = await limiter.check_rate_limit("10.0.0.2")
        assert result is True


# ── Status Tests ──

class TestStatus:
    """状态查询测试"""

    @pytest.mark.asyncio
    async def test_get_status(self, limiter):
        """状态查询"""
        status = limiter.get_status()

        assert "tasks" in status
        assert "llm" in status
        assert "downloads" in status
        assert "stats" in status

        assert status["tasks"]["max"] == 2
        assert status["llm"]["max"] == 3
        assert status["downloads"]["max"] == 1

    @pytest.mark.asyncio
    async def test_stats_tracking(self, limiter):
        """统计计数"""
        await limiter.acquire_task("t1")
        await limiter.acquire_task("t2")
        await limiter.acquire_task("t3")  # 被拒绝

        status = limiter.get_status()
        assert status["stats"]["tasks_acquired"] == 2
        assert status["stats"]["tasks_rejected"] == 1

        limiter.release_task("t1")
        limiter.release_task("t2")

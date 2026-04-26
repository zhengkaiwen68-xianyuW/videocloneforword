"""
钩子拆解器单元测试

测试 HookDeconstructor 的核心逻辑：
- 单个钩子拆解
- 批量拆解
- 钩子文本提取
- 错误处理
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from persona_engine.technique.hook_deconstructor import HookDeconstructor
from persona_engine.core.types import HookAnalysis, HookType


# ── Mock LLM Provider ──

class MockLLMProvider:
    """模拟 LLM 返回结构化钩子分析"""

    def __init__(self, response=None):
        self.response = response or {
            "hook_type": "reverse_logic",
            "psychological_mechanism": "认知失调：打破用户固有认知",
            "structural_formula": "{常识} + 根本不是{常识}",
            "why_it_works": "利用认知偏差，让用户产生好奇",
            "reconstruction_template": "用'根本不用X'的句式替换X",
        }

    async def generate(self, prompt, system_prompt=None, **kwargs):
        return str(self.response)

    async def generate_json(self, prompt, system_prompt=None, **kwargs):
        return self.response


class FailingLLMProvider:
    """模拟 LLM 调用失败"""

    async def generate(self, prompt, system_prompt=None, **kwargs):
        raise RuntimeError("API connection failed")

    async def generate_json(self, prompt, system_prompt=None, **kwargs):
        raise RuntimeError("API connection failed")


# ── Tests ──

class TestHookDeconstruct:
    """单个钩子拆解测试"""

    @pytest.mark.asyncio
    async def test_deconstruct_basic(self):
        """基本拆解流程"""
        mock_llm = MockLLMProvider()
        deconstructor = HookDeconstructor(llm_provider=mock_llm)

        result = await deconstructor.deconstruct(
            hook_text="Excel根本不用学",
            full_text="Excel根本不用学，你只需要掌握这3个函数...",
            source_video_url="https://bilibili.com/video/BV123",
            persona_id="test_persona",
        )

        assert isinstance(result, HookAnalysis)
        assert result.hook_text == "Excel根本不用学"
        assert result.hook_type == HookType.REVERSE_LOGIC
        assert "认知失调" in result.psychological_mechanism
        assert result.source_video_url == "https://bilibili.com/video/BV123"
        assert result.persona_id == "test_persona"

    @pytest.mark.asyncio
    async def test_deconstruct_all_hook_types(self):
        """测试所有 7 种钩子类型都能正确解析"""
        hook_types = [
            "reverse_logic", "pain_point", "benefit_bomb",
            "suspense_cutoff", "authority_subvert", "data_impact", "identity_label",
        ]

        for ht in hook_types:
            mock_llm = MockLLMProvider(response={
                "hook_type": ht,
                "psychological_mechanism": "test",
                "structural_formula": "test",
                "why_it_works": "test",
                "reconstruction_template": "test",
            })
            deconstructor = HookDeconstructor(llm_provider=mock_llm)
            result = await deconstructor.deconstruct(hook_text="测试文案")
            assert result.hook_type.value == ht

    @pytest.mark.asyncio
    async def test_deconstruct_invalid_hook_type(self):
        """无效钩子类型应回退到 reverse_logic"""
        mock_llm = MockLLMProvider(response={
            "hook_type": "invalid_type",
            "psychological_mechanism": "test",
            "structural_formula": "test",
            "why_it_works": "test",
            "reconstruction_template": "test",
        })
        deconstructor = HookDeconstructor(llm_provider=mock_llm)
        result = await deconstructor.deconstruct(hook_text="测试")
        assert result.hook_type == HookType.REVERSE_LOGIC

    @pytest.mark.asyncio
    async def test_deconstruct_llm_failure(self):
        """LLM 失败时应返回默认分析结果"""
        deconstructor = HookDeconstructor(llm_provider=FailingLLMProvider())
        result = await deconstructor.deconstruct(hook_text="测试文案")

        assert isinstance(result, HookAnalysis)
        assert result.hook_text == "测试文案"
        assert result.hook_type == HookType.REVERSE_LOGIC
        assert "分析失败" in result.psychological_mechanism


class TestHookBatchDeconstruct:
    """批量拆解测试"""

    @pytest.mark.asyncio
    async def test_batch_deconstruct_basic(self):
        """基本批量拆解"""
        mock_llm = MockLLMProvider()
        deconstructor = HookDeconstructor(llm_provider=mock_llm)

        hooks = ["Excel不用学", "你还在用这种方法？", "3秒搞定"]
        results = await deconstructor.batch_deconstruct(hook_texts=hooks)

        assert len(results) == 3
        for r in results:
            assert isinstance(r, HookAnalysis)

    @pytest.mark.asyncio
    async def test_batch_deconstruct_with_context(self):
        """带上下文的批量拆解"""
        mock_llm = MockLLMProvider()
        deconstructor = HookDeconstructor(llm_provider=mock_llm)

        hooks = ["钩子1", "钩子2"]
        full_texts = ["完整文本1...", "完整文本2..."]
        urls = ["https://bilibili.com/v1", "https://bilibili.com/v2"]

        results = await deconstructor.batch_deconstruct(
            hook_texts=hooks,
            full_texts=full_texts,
            source_video_urls=urls,
            persona_id="p1",
        )

        assert len(results) == 2
        assert results[0].source_video_url == "https://bilibili.com/v1"
        assert results[1].source_video_url == "https://bilibili.com/v2"
        assert all(r.persona_id == "p1" for r in results)

    @pytest.mark.asyncio
    async def test_batch_deconstruct_empty_list(self):
        """空列表应返回空结果"""
        mock_llm = MockLLMProvider()
        deconstructor = HookDeconstructor(llm_provider=mock_llm)
        results = await deconstructor.batch_deconstruct(hook_texts=[])
        assert results == []


class TestHookTextExtraction:
    """钩子文本提取测试"""

    def test_extract_short_text(self):
        """短文本直接返回"""
        text = "这是一段短文案"
        result = HookDeconstructor.extract_hook_from_text(text, max_chars=50)
        assert result == text

    def test_extract_with_punctuation(self):
        """在标点处截断"""
        text = "Excel根本不用学，你只需要掌握这3个函数就能搞定90%的工作，剩下的以后再说"
        result = HookDeconstructor.extract_hook_from_text(text, max_chars=50)
        assert len(result) <= 51  # 包含标点
        assert result.endswith("，") or result.endswith("。") or len(result) <= 50

    def test_extract_no_punctuation(self):
        """无标点时按字符数截断"""
        text = "这是一段很长很长很长很长很长很长很长很长很长很长很长很长的文案没有任何标点符号"
        result = HookDeconstructor.extract_hook_from_text(text, max_chars=20)
        assert len(result) == 20

    def test_extract_empty_text(self):
        """空文本返回空"""
        result = HookDeconstructor.extract_hook_from_text("")
        assert result == ""

    def test_extract_exactly_max_chars(self):
        """恰好等于 max_chars 的文本"""
        text = "A" * 50
        result = HookDeconstructor.extract_hook_from_text(text, max_chars=50)
        assert result == text

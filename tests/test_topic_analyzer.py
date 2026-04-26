"""
选题技法分析器单元测试

测试 TopicAnalyzer 的核心逻辑：
- 多文本分析
- 单文本分析
- 空输入处理
- 错误处理
"""

import pytest
from persona_engine.technique.topic_analyzer import TopicAnalyzer
from persona_engine.core.types import TopicTechnique


# ── Mock LLM Provider ──

MOCK_TOPIC_RESULT = {
    "angle_patterns": ["反常识切入", "痛点前置", "数据碾压"],
    "pain_points": ["职场效率焦虑", "学习成本高", "时间不够用"],
    "topic_formulas": ["{常识} + 根本不是{常识}", "你以为{X}其实{Y}"],
    "selection_criteria": ["与职场效率相关", "有明确的痛点"],
    "avoid_patterns": ["政治敏感话题", "纯娱乐八卦"],
}


class MockTopicLLM:
    async def generate(self, prompt, system_prompt=None, **kwargs):
        return str(MOCK_TOPIC_RESULT)

    async def generate_json(self, prompt, system_prompt=None, **kwargs):
        return MOCK_TOPIC_RESULT


class FailingLLM:
    async def generate(self, prompt, system_prompt=None, **kwargs):
        raise RuntimeError("API error")

    async def generate_json(self, prompt, system_prompt=None, **kwargs):
        raise RuntimeError("API error")


# ── Tests ──

class TestTopicAnalyzer:
    """选题技法分析测试"""

    @pytest.mark.asyncio
    async def test_analyze_basic(self):
        """基本分析流程"""
        analyzer = TopicAnalyzer(llm_provider=MockTopicLLM())

        texts = [
            "Excel根本不用学，你只需要这3个函数...",
            "月薪3000和30000的人，区别只有这一点...",
        ]

        result = await analyzer.analyze(texts)

        assert isinstance(result, TopicTechnique)
        assert len(result.angle_patterns) == 3
        assert "反常识切入" in result.angle_patterns
        assert len(result.pain_points) == 3
        assert len(result.topic_formulas) == 2
        assert len(result.selection_criteria) == 2
        assert len(result.avoid_patterns) == 2

    @pytest.mark.asyncio
    async def test_analyze_empty_texts(self):
        """空文本列表应返回默认画像"""
        analyzer = TopicAnalyzer(llm_provider=MockTopicLLM())
        result = await analyzer.analyze([])

        assert isinstance(result, TopicTechnique)
        assert result.angle_patterns == []

    @pytest.mark.asyncio
    async def test_analyze_llm_failure(self):
        """LLM 失败时应返回默认画像"""
        analyzer = TopicAnalyzer(llm_provider=FailingLLM())
        result = await analyzer.analyze(["测试文本"])

        assert isinstance(result, TopicTechnique)
        assert result.angle_patterns == []

    @pytest.mark.asyncio
    async def test_analyze_single(self):
        """单文本分析"""
        analyzer = TopicAnalyzer(llm_provider=MockTopicLLM())
        result = await analyzer.analyze_single("这是一个测试文本")

        assert isinstance(result, TopicTechnique)
        assert len(result.angle_patterns) > 0


class TestTopicTechniqueSerialization:
    """TopicTechnique 序列化测试"""

    def test_from_dict(self):
        """从字典创建"""
        result = TopicTechnique.from_dict(MOCK_TOPIC_RESULT)
        assert result.angle_patterns == MOCK_TOPIC_RESULT["angle_patterns"]
        assert result.pain_points == MOCK_TOPIC_RESULT["pain_points"]

    def test_to_dict(self):
        """序列化为字典"""
        tech = TopicTechnique(
            angle_patterns=["反常识"],
            pain_points=["焦虑"],
            topic_formulas=["公式1"],
            selection_criteria=["标准1"],
            avoid_patterns=["禁区1"],
        )
        d = tech.to_dict()
        assert d["angle_patterns"] == ["反常识"]
        assert d["pain_points"] == ["焦虑"]

    def test_from_dict_missing_fields(self):
        """部分字段缺失时使用默认值"""
        result = TopicTechnique.from_dict({"angle_patterns": ["test"]})
        assert result.angle_patterns == ["test"]
        assert result.pain_points == []

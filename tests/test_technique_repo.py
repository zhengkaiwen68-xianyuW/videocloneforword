"""
技法知识库单元测试

测试 TechniqueKnowledgeBase 的业务逻辑：
- 钩子推荐
- 钩子统计
- 技法画像摘要
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from persona_engine.technique.technique_repo import TechniqueKnowledgeBase
from persona_engine.core.types import HookAnalysis, HookType, TopicTechnique


# ── Mock Data ──

def make_hook(hook_type=HookType.REVERSE_LOGIC, text="测试钩子", persona_id="p1"):
    return HookAnalysis(
        hook_text=text,
        hook_type=hook_type,
        psychological_mechanism="认知失调",
        structural_formula="{常识} + 不是{常识}",
        why_it_works="打破认知",
        reconstruction_template="替换模板",
        source_video_url="",
        persona_id=persona_id,
    )


# ── Mock Repository ──

class MockTechniqueRepo:
    def __init__(self, hooks=None, topic_technique=None):
        self.hooks = hooks or []
        self.topic_technique = topic_technique

    async def get_hooks_by_persona(self, persona_id):
        return [h for h in self.hooks if h.persona_id == persona_id]

    async def get_hooks_by_type(self, hook_type):
        return [h for h in self.hooks if h.hook_type.value == hook_type]

    async def search_hooks(self, query, limit=10):
        if not query:
            return self.hooks[:limit]
        return [h for h in self.hooks if query.lower() in h.hook_text.lower()][:limit]

    async def get_topic_technique(self, persona_id):
        return self.topic_technique

    async def get_structures_by_persona(self, persona_id):
        return []


# ── Tests ──

class TestRecommendHooks:
    """钩子推荐测试"""

    @pytest.mark.asyncio
    async def test_recommend_by_persona(self):
        """按人格推荐"""
        hooks = [
            make_hook(text="钩子1", persona_id="p1"),
            make_hook(text="钩子2", persona_id="p1"),
            make_hook(text="钩子3", persona_id="p2"),
        ]
        repo = MockTechniqueRepo(hooks=hooks)
        kb = TechniqueKnowledgeBase(repo=repo)

        results = await kb.recommend_hooks(target_persona="p1")
        assert len(results) == 2
        assert all(h.persona_id == "p1" for h in results)

    @pytest.mark.asyncio
    async def test_recommend_by_hook_type(self):
        """按钩子类型推荐"""
        hooks = [
            make_hook(hook_type=HookType.REVERSE_LOGIC, text="反逻辑钩子"),
            make_hook(hook_type=HookType.PAIN_POINT, text="痛点钩子"),
            make_hook(hook_type=HookType.REVERSE_LOGIC, text="反逻辑钩子2"),
        ]
        repo = MockTechniqueRepo(hooks=hooks)
        kb = TechniqueKnowledgeBase(repo=repo)

        results = await kb.recommend_hooks(hook_type="reverse_logic")
        assert len(results) == 2
        assert all(h.hook_type == HookType.REVERSE_LOGIC for h in results)

    @pytest.mark.asyncio
    async def test_recommend_by_topic(self):
        """按关键词推荐"""
        hooks = [
            make_hook(text="Excel不用学"),
            make_hook(text="PPT一键美化"),
            make_hook(text="Excel快捷键"),
        ]
        repo = MockTechniqueRepo(hooks=hooks)
        kb = TechniqueKnowledgeBase(repo=repo)

        results = await kb.recommend_hooks(topic="Excel")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_recommend_empty(self):
        """无匹配时返回空"""
        repo = MockTechniqueRepo(hooks=[])
        kb = TechniqueKnowledgeBase(repo=repo)

        results = await kb.recommend_hooks()
        assert results == []


class TestHookStats:
    """钩子统计测试"""

    @pytest.mark.asyncio
    async def test_stats_basic(self):
        """基本统计"""
        hooks = [
            make_hook(hook_type=HookType.REVERSE_LOGIC, persona_id="p1"),
            make_hook(hook_type=HookType.REVERSE_LOGIC, persona_id="p1"),
            make_hook(hook_type=HookType.PAIN_POINT, persona_id="p1"),
        ]
        repo = MockTechniqueRepo(hooks=hooks)
        kb = TechniqueKnowledgeBase(repo=repo)

        stats = await kb.get_hook_stats("p1")
        assert stats["total"] == 3
        assert stats["type_distribution"]["reverse_logic"] == 2
        assert stats["type_distribution"]["pain_point"] == 1
        assert stats["most_used_type"] == "reverse_logic"

    @pytest.mark.asyncio
    async def test_stats_empty(self):
        """空统计"""
        repo = MockTechniqueRepo(hooks=[])
        kb = TechniqueKnowledgeBase(repo=repo)

        stats = await kb.get_hook_stats("p1")
        assert stats["total"] == 0
        assert stats["most_used_type"] is None


class TestPersonaSummary:
    """人格技法摘要测试"""

    @pytest.mark.asyncio
    async def test_summary_with_data(self):
        """有数据的摘要"""
        hooks = [make_hook(persona_id="p1")]
        topic = TopicTechnique(
            angle_patterns=["反常识"],
            pain_points=["焦虑"],
            topic_formulas=["公式"],
            selection_criteria=["标准"],
            avoid_patterns=["禁区"],
        )
        repo = MockTechniqueRepo(hooks=hooks, topic_technique=topic)
        kb = TechniqueKnowledgeBase(repo=repo)

        summary = await kb.get_persona_techniques_summary("p1")
        assert summary["topic_techniques"] is not None
        assert summary["hook_stats"]["total"] == 1
        assert summary["structure_count"] == 0

    @pytest.mark.asyncio
    async def test_summary_no_topic(self):
        """无选题技法时"""
        repo = MockTechniqueRepo(hooks=[], topic_technique=None)
        kb = TechniqueKnowledgeBase(repo=repo)

        summary = await kb.get_persona_techniques_summary("p1")
        assert summary["topic_techniques"] is None

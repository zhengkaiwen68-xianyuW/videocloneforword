"""
技法知识库（业务逻辑层）

封装 TechniqueRepository，提供技法组合推荐、去重合并等高级能力。
"""

import logging
from typing import Any

from ..core.types import HookAnalysis, HookType, TopicTechnique, ContentStructureMap
from ..storage.persona_repo import TechniqueRepository


logger = logging.getLogger(__name__)


class TechniqueKnowledgeBase:
    """
    技法知识库

    基于 TechniqueRepository 封装业务逻辑，提供：
    - 技法组合推荐
    - 技法去重与合并
    - 统计分析
    """

    def __init__(self, repo: TechniqueRepository | None = None):
        self.repo = repo or TechniqueRepository()

    async def recommend_hooks(
        self,
        topic: str = "",
        target_persona: str = "",
        hook_type: str = "",
        limit: int = 5,
    ) -> list[HookAnalysis]:
        """
        根据条件推荐最合适的钩子技法

        Args:
            topic: 选题关键词（用于搜索匹配）
            target_persona: 目标人格 ID（限定范围）
            hook_type: 钩子类型偏好
            limit: 返回数量

        Returns:
            推荐的 HookAnalysis 列表
        """
        # 优先按人格筛选
        if target_persona:
            hooks = await self.repo.get_hooks_by_persona(target_persona)
        elif hook_type:
            hooks = await self.repo.get_hooks_by_type(hook_type)
        elif topic:
            hooks = await self.repo.search_hooks(topic, limit=limit * 2)
        else:
            # 无条件，返回最新的
            hooks = await self.repo.search_hooks("", limit=limit)

        # 按类型过滤
        if hook_type:
            hooks = [h for h in hooks if h.hook_type.value == hook_type]

        # 按关键词过滤
        if topic:
            topic_lower = topic.lower()
            hooks = [
                h for h in hooks
                if topic_lower in h.hook_text.lower()
                or topic_lower in h.structural_formula.lower()
            ]

        return hooks[:limit]

    async def get_hook_stats(self, persona_id: str) -> dict[str, Any]:
        """
        获取指定人格的钩子技法统计

        Returns:
            {hook_type: count} 分布 + 总数
        """
        hooks = await self.repo.get_hooks_by_persona(persona_id)

        type_counts: dict[str, int] = {}
        for h in hooks:
            key = h.hook_type.value
            type_counts[key] = type_counts.get(key, 0) + 1

        return {
            "total": len(hooks),
            "type_distribution": type_counts,
            "most_used_type": max(type_counts, key=type_counts.get) if type_counts else None,
        }

    async def get_persona_techniques_summary(self, persona_id: str) -> dict[str, Any]:
        """
        获取人格的完整技法画像摘要

        Returns:
            包含 topic_techniques, hook_stats, structure_count 的字典
        """
        topic_tech = await self.repo.get_topic_technique(persona_id)
        hook_stats = await self.get_hook_stats(persona_id)
        structures = await self.repo.get_structures_by_persona(persona_id)

        return {
            "topic_techniques": topic_tech.to_dict() if topic_tech else None,
            "hook_stats": hook_stats,
            "structure_count": len(structures),
        }

"""
内容结构映射器

分析完整 ASR 文本，提取内容操控地图。
"""

import logging
from typing import Any

from ..core.types import ContentStructureMap, HookAnalysis, HookType
from ..llm.factory import create_llm_provider
from .prompt_library import build_structure_map_prompt
from .hook_deconstructor import HookDeconstructor


logger = logging.getLogger(__name__)


class StructureMapper:
    """内容结构映射器"""

    def __init__(self, llm_provider=None):
        self.llm = llm_provider or create_llm_provider()
        self.hook_deconstructor = HookDeconstructor(llm_provider)

    async def map_structure(
        self,
        full_text: str,
        timestamps: list[dict] | None = None,
        hook_analysis: HookAnalysis | None = None,
        source_video_url: str = "",
        persona_id: str = "",
    ) -> ContentStructureMap:
        """
        分析完整文本，生成内容结构映射

        Args:
            full_text: 完整 ASR 文本
            timestamps: 时间戳列表（可选）
            hook_analysis: 已有的钩子分析（可选，没有会自动提取）
            source_video_url: 来源视频 URL
            persona_id: 关联人格 ID

        Returns:
            ContentStructureMap 完整操控地图
        """
        # 如果没有钩子分析，自动提取
        if hook_analysis is None:
            from .hook_deconstructor import HookDeconstructor
            hook_text = HookDeconstructor.extract_hook_from_text(full_text)
            hook_analysis = await self.hook_deconstructor.deconstruct(
                hook_text=hook_text,
                full_text=full_text,
                source_video_url=source_video_url,
                persona_id=persona_id,
            )

        prompt = build_structure_map_prompt(full_text, timestamps)
        system_prompt = "你是一位短视频内容结构分析师，擅长拆解视频的操控地图。"

        try:
            result = await self.llm.generate_json(
                prompt=prompt,
                system_prompt=system_prompt,
            )

            return ContentStructureMap(
                hook=hook_analysis,
                credibility_build=result.get("credibility_build", ""),
                pain_amplification=result.get("pain_amplification", ""),
                information_density_curve=result.get("information_density_curve", []),
                emotion_curve=result.get("emotion_curve", []),
                cta_pattern=result.get("cta_pattern", ""),
                closing_emotion=result.get("closing_emotion", ""),
                persona_id=persona_id,
                source_video_url=source_video_url,
            )
        except Exception as e:
            logger.error(f"Structure mapping failed: {e}")
            return ContentStructureMap(
                hook=hook_analysis,
                persona_id=persona_id,
                source_video_url=source_video_url,
            )

    async def batch_map(
        self,
        texts: list[str],
        source_video_urls: list[str] | None = None,
        persona_id: str = "",
    ) -> list[ContentStructureMap]:
        """
        批量映射多个视频的内容结构

        Args:
            texts: 多个完整视频文本
            source_video_urls: 对应的视频 URL 列表
            persona_id: 关联人格 ID

        Returns:
            ContentStructureMap 列表
        """
        results = []
        for i, text in enumerate(texts):
            video_url = source_video_urls[i] if source_video_urls and i < len(source_video_urls) else ""
            structure = await self.map_structure(
                full_text=text,
                source_video_url=video_url,
                persona_id=persona_id,
            )
            results.append(structure)
        return results

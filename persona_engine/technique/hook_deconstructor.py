"""
黄金3秒钩子拆解器

拆解视频开头的 Hook 文案，提取结构化技法信息。
"""

import logging
from typing import Any

from ..core.types import HookAnalysis, HookType
from ..llm.factory import create_llm_provider
from .prompt_library import build_hook_deconstruct_prompt


logger = logging.getLogger(__name__)


class HookDeconstructor:
    """黄金3秒钩子拆解器"""

    def __init__(self, llm_provider=None):
        self.llm = llm_provider or create_llm_provider()

    async def deconstruct(
        self,
        hook_text: str,
        full_text: str = "",
        source_video_url: str = "",
        persona_id: str = "",
    ) -> HookAnalysis:
        """
        拆解单个钩子文案

        Args:
            hook_text: 视频开头 3 秒的 ASR 文本
            full_text: 完整视频文本（可选，提供上下文）
            source_video_url: 来源视频 URL
            persona_id: 关联人格 ID

        Returns:
            HookAnalysis 结构化拆解
        """
        prompt = build_hook_deconstruct_prompt(hook_text, full_text)
        system_prompt = "你是一位短视频流量密码研究专家，专门拆解钩子的底层机制。"

        try:
            result = await self.llm.generate_json(
                prompt=prompt,
                system_prompt=system_prompt,
            )

            # 验证 hook_type
            hook_type_str = result.get("hook_type", "reverse_logic")
            try:
                hook_type = HookType(hook_type_str)
            except ValueError:
                logger.warning(f"Invalid hook_type '{hook_type_str}', defaulting to reverse_logic")
                hook_type = HookType.REVERSE_LOGIC

            return HookAnalysis(
                hook_text=hook_text,
                hook_type=hook_type,
                psychological_mechanism=result.get("psychological_mechanism", ""),
                structural_formula=result.get("structural_formula", ""),
                why_it_works=result.get("why_it_works", ""),
                reconstruction_template=result.get("reconstruction_template", ""),
                source_video_url=source_video_url,
                persona_id=persona_id,
            )
        except Exception as e:
            logger.error(f"Hook deconstruction failed: {e}")
            return HookAnalysis(
                hook_text=hook_text,
                hook_type=HookType.REVERSE_LOGIC,
                psychological_mechanism="分析失败",
                structural_formula="",
                why_it_works="",
                reconstruction_template="",
                source_video_url=source_video_url,
                persona_id=persona_id,
            )

    async def batch_deconstruct(
        self,
        hook_texts: list[str],
        full_texts: list[str] | None = None,
        source_video_urls: list[str] | None = None,
        persona_id: str = "",
    ) -> list[HookAnalysis]:
        """
        批量拆解钩子

        Args:
            hook_texts: 多个视频开头文案
            full_texts: 对应的完整文本列表
            source_video_urls: 对应的视频 URL 列表
            persona_id: 关联人格 ID

        Returns:
            HookAnalysis 列表
        """
        results = []
        for i, hook_text in enumerate(hook_texts):
            full_text = full_texts[i] if full_texts and i < len(full_texts) else ""
            video_url = source_video_urls[i] if source_video_urls and i < len(source_video_urls) else ""

            analysis = await self.deconstruct(
                hook_text=hook_text,
                full_text=full_text,
                source_video_url=video_url,
                persona_id=persona_id,
            )
            results.append(analysis)

        return results

    @staticmethod
    def extract_hook_from_text(text: str, max_chars: int = 50) -> str:
        """
        从完整文本中提取前 3 秒内容（约 15-25 个汉字）

        基于标点符号或字符数截取开头。
        """
        text = text.strip()
        if len(text) <= max_chars:
            return text

        # 尝试在标点处截断
        for punct in ["，", "。", "！", "？", ",", ".", "!", "?"]:
            idx = text.find(punct)
            if 5 < idx <= max_chars:
                return text[:idx + 1]

        return text[:max_chars]

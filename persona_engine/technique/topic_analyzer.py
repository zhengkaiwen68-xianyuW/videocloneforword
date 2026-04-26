"""
选题技法分析器

从同一 UP 主的多篇 ASR 文本中提炼选题技法画像。
"""

import logging
from typing import Any

from ..core.types import TopicTechnique
from ..llm.factory import create_llm_provider
from .prompt_library import build_topic_analysis_prompt


logger = logging.getLogger(__name__)


class TopicAnalyzer:
    """选题技法分析器"""

    def __init__(self, llm_provider=None):
        self.llm = llm_provider or create_llm_provider()

    async def analyze(self, texts: list[str]) -> TopicTechnique:
        """
        从多篇 ASR 文本中提炼选题技法画像

        Args:
            texts: 同一 UP 主的多篇 ASR 文本

        Returns:
            TopicTechnique 结构化画像
        """
        if not texts:
            return TopicTechnique()

        prompt = build_topic_analysis_prompt(texts)
        system_prompt = "你是一位短视频内容策略分析师，擅长从文案中提炼选题规律。"

        try:
            result = await self.llm.generate_json(
                prompt=prompt,
                system_prompt=system_prompt,
            )
            return TopicTechnique.from_dict(result)
        except Exception as e:
            logger.error(f"Topic analysis failed: {e}")
            return TopicTechnique()

    async def analyze_single(self, text: str) -> TopicTechnique:
        """分析单篇文本的选题特征（精度较低，适合快速预览）"""
        return await self.analyze([text])

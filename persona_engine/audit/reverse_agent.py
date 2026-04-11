"""
反向推导 Agent

根据生成的文案反向提取人格特征，用于与原始画像对比
"""

import json
import logging
from typing import Any

from ..core.types import PersonalityProfile, LogicArchitecture, TemporalPattern
from ..core.exceptions import ReverseExtractionError
from ..rewrite.minimax_adapter import MiniMaxAdapter


logger = logging.getLogger(__name__)


class ReverseAgent:
    """
    反向推导 Agent

    功能：
    1. 接收重写后的文案
    2. 调用 AI 从文案中反向提取人格特征
    3. 与原始人格画像对比，返回推测的特征

    核心算法：
    - 输入：重写文案 + 原始人格画像
    - 过程：AI 分析文风中哪些特征被成功复现
    - 输出：推测的人格画像 + 匹配度分析
    """

    def __init__(self, llm_adapter: MiniMaxAdapter):
        """
        初始化反向推导 Agent

        Args:
            llm_adapter: MiniMax 适配器实例
        """
        self.llm_adapter = llm_adapter
        self.model_adapter = llm_adapter  # 别名，兼容 Scorer 的调用方式

    async def reverse_extract(
        self,
        text: str,
        original_profile: PersonalityProfile | None = None,
    ) -> dict[str, Any]:
        """
        反向提取人格特征

        Args:
            text: 需要分析的文案
            original_profile: 原始人格画像（用于对比参考）

        Returns:
            {
                "extracted_profile": {...},  # 推测的人格特征
                "matched_features": [...],   # 成功匹配的特征
                "missing_features": [...],  # 缺失的特征
                "analysis": "详细分析"
            }

        Raises:
            ReverseExtractionError: 提取失败
        """
        try:
            # 构建提示词
            prompt = self._build_reverse_prompt(text, original_profile)

            # 调用 AI 提取
            result = await self.llm_adapter.reverse_extract(text)

            # 解析结果
            extracted = self._parse_extracted_features(result)

            # 对比分析
            comparison = self._compare_with_original(
                extracted, original_profile
            ) if original_profile else {}

            return {
                "extracted_profile": extracted,
                "matched_features": comparison.get("matched", []),
                "missing_features": comparison.get("missing", []),
                "analysis": comparison.get("analysis", ""),
                "confidence": result.get("confidence", 0.8),
            }

        except Exception as e:
            raise ReverseExtractionError(
                message=f"Reverse extraction failed: {str(e)}",
                text_length=len(text),
                details={"error_type": type(e).__name__},
            )

    def _build_reverse_prompt(
        self,
        text: str,
        original_profile: PersonalityProfile | None,
    ) -> str:
        """
        构建反向推导提示词

        Args:
            text: 待分析文案
            original_profile: 原始画像（可选）

        Returns:
            提示词字符串
        """
        base_prompt = f"""## 任务
分析以下文案，推测该作者的人格特征。

## 待分析文案
{text}

## 输出格式
严格以 JSON 格式返回：
{{
    "verbal_tics": ["推测的口头禅列表"],
    "grammar_prefs": ["推测的语法偏好"],
    "logic_architecture": {{
        "opening_style": "推测的开场风格",
        "transition_patterns": ["推测的过渡模式"],
        "closing_style": "推测的结尾风格"
    }},
    "speech_rhythm": "推测的语速节奏(fast/medium/slow)",
    "confidence": 0.85
}}
"""

        if original_profile:
            base_prompt += f"""

## 参考：原始人格画像
- 口头禅：{', '.join(original_profile.verbal_tics[:5]) if original_profile.verbal_tics else '无'}
- 语法偏好：{', '.join(original_profile.grammar_prefs[:3]) if original_profile.grammar_prefs else '无'}
- 开场风格：{original_profile.logic_architecture.opening_style}
- 结尾风格：{original_profile.logic_architecture.closing_style}

请在分析时参考上述原始画像，重点判断这些特征是否在文案中得到体现。
"""

        return base_prompt

    def _parse_extracted_features(self, result: dict[str, Any]) -> dict[str, Any]:
        """
        解析 AI 返回的提取结果

        Args:
            result: AI 返回的字典

        Returns:
            标准化的人格特征字典
        """
        extracted = {
            "verbal_tics": result.get("verbal_tics", []),
            "grammar_prefs": result.get("grammar_prefs", []),
            "logic_architecture": result.get("logic_architecture", {}),
            "speech_rhythm": result.get("speech_rhythm", "medium"),
            "confidence": result.get("confidence", 0.5),
        }

        # 确保逻辑架构结构完整
        if isinstance(extracted["logic_architecture"], dict):
            arch = extracted["logic_architecture"]
            extracted["logic_architecture"] = {
                "opening_style": arch.get("opening_style", "未知"),
                "transition_patterns": arch.get("transition_patterns", []),
                "closing_style": arch.get("closing_style", "未知"),
                "topic_organization": arch.get("topic_organization", "未知"),
            }

        return extracted

    def _compare_with_original(
        self,
        extracted: dict[str, Any],
        original: PersonalityProfile,
    ) -> dict[str, Any]:
        """
        对比推测特征与原始画像

        Args:
            extracted: 推测的特征
            original: 原始人格画像

        Returns:
            对比结果
        """
        matched = []
        missing = []

        # 口头禅匹配检查
        original_tics = set(original.verbal_tics)
        extracted_tics = set(extracted.get("verbal_tics", []))
        tic_overlap = original_tics & extracted_tics
        if tic_overlap:
            matched.append(f"口头禅匹配: {', '.join(tic_overlap)}")
        else:
            missing.append("口头禅未匹配")

        # 语法偏好匹配检查
        original_prefs = set(original.grammar_prefs)
        extracted_prefs = set(extracted.get("grammar_prefs", []))
        if original_prefs & extracted_prefs:
            matched.append("部分语法偏好匹配")
        elif original_prefs:
            missing.append("语法偏好未匹配")

        # 逻辑架构匹配
        orig_arch = original.logic_architecture
        ext_arch = extracted.get("logic_architecture", {})

        if orig_arch.opening_style == ext_arch.get("opening_style"):
            matched.append("开场风格匹配")
        if orig_arch.closing_style == ext_arch.get("closing_style"):
            matched.append("结尾风格匹配")

        # 节奏匹配
        if original.temporal_patterns.speech_rhythm == extracted.get("speech_rhythm"):
            matched.append("节奏风格匹配")

        analysis = self._generate_analysis(matched, missing, extracted, original)

        return {
            "matched": matched,
            "missing": missing,
            "analysis": analysis,
        }

    def _generate_analysis(
        self,
        matched: list[str],
        missing: list[str],
        extracted: dict[str, Any],
        original: PersonalityProfile,
    ) -> str:
        """
        生成详细分析文本

        Args:
            matched: 匹配的特征
            missing: 缺失的特征
            extracted: 推测特征
            original: 原始画像

        Returns:
            分析文本
        """
        lines = []

        # 整体评价
        match_rate = len(matched) / (len(matched) + len(missing) + 1)
        if match_rate > 0.7:
            lines.append(f"整体评价：人格复现效果良好（匹配率 {match_rate:.0%}）")
        elif match_rate > 0.4:
            lines.append(f"整体评价：人格复现效果一般（匹配率 {match_rate:.0%}）")
        else:
            lines.append(f"整体评价：人格复现效果较差（匹配率 {match_rate:.0%}）")

        # 详细分析
        if matched:
            lines.append(f"✓ 已复现特征：{'；'.join(matched)}")

        if missing:
            lines.append(f"✗ 未复现特征：{'；'.join(missing)}")

        # 推测的新特征
        extracted_tics = set(extracted.get("verbal_tics", []))
        original_tics = set(original.verbal_tics)
        new_tics = extracted_tics - original_tics
        if new_tics:
            lines.append(f"？推测新特征：{', '.join(new_tics)}（原始画像中未记录）")

        return "\n".join(lines)

    async def batch_reverse_extract(
        self,
        texts: list[str],
        original_profile: PersonalityProfile | None = None,
    ) -> list[dict[str, Any]]:
        """
        批量反向提取

        Args:
            texts: 文案列表
            original_profile: 原始人格画像

        Returns:
            各文案的提取结果列表
        """
        results = []
        for text in texts:
            try:
                result = await self.reverse_extract(text, original_profile)
                result["success"] = True
            except ReverseExtractionError as e:
                result = {
                    "success": False,
                    "error": str(e),
                    "extracted_profile": None,
                }
            results.append(result)

        return results

    def extract_verbal_tics_only(self, text: str) -> list[str]:
        """
        快速提取口头禅（不调用 AI，基于规则）

        Args:
            text: 文案文本

        Returns:
            识别出的口头禅列表
        """
        # 常见语气词模式
        tic_patterns = [
            "然后", "其实", "那个", "好吧", "嗯", "啊", "呢",
            "我觉得", "应该", "可能", "大概", "反正", "所以",
            "但是", "不过", "而且", "然后呢", "不是", "对",
        ]

        found_tics = []
        for pattern in tic_patterns:
            if pattern in text:
                found_tics.append(pattern)

        return found_tics

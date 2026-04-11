"""
术语锁定模块 - 动态识别和保护专业术语

确保游戏装备、参数，专业动作等词汇在重写后变动率为 0
"""

import re
from dataclasses import dataclass, field
from typing import Set


# 常见领域术语模式
DOMAIN_TERM_PATTERNS = {
    # 游戏装备/道具
    r"[\u4e00-\u9fa5a-zA-Z]+级装备",
    r"[\u4e00-\u9fa5]+之刃",
    r"[\u4e00-\u9fa5]+之甲",
    r"紫色装备",
    r"金色装备",
    r"史诗级",
    r"传说级",
    # 游戏数值/参数
    r"\d+%?攻击",
    r"防御力\d+",
    r"生命值\d+",
    r"法力值\d+",
    r"cd[：:]?\d+秒",
    r"冷却\d+秒",
    r"伤害\d+",
    # 专业动作/技能
    r"平A",
    r"普攻",
    r"重击",
    r"闪避",
    r"格挡",
    r"连招",
    r"起手",
    r"收招",
    # 游戏机制
    r"暴击率",
    r"命中率",
    r"闪避率",
    r"攻速",
    r"移速",
    r"韧性",
    # 特定游戏词汇
    r"深渊",
    r"副本",
    r"团本",
    r"BOSS",
    r"MVP",
    r"SSS",
}


@dataclass
class TermLockResult:
    """术语锁定结果"""
    locked_terms: Set[str]                              # 锁定的术语集合
    locked_map: dict[str, str]                         # 占位符 -> 原始术语的映射
    original_text: str                                  # 原始文本
    protected_text: str                                 # 保护后的文本


class TermLock:
    """
    术语锁定器（基础版）

    功能：
    1. 自动识别文本中的专业术语
    2. 用占位符替换术语，防止在重写时被修改
    3. 提供恢复机制，将占位符还原为原始术语
    """

    def __init__(self, custom_patterns: list[str] | None = None):
        self.patterns: list[re.Pattern] = []
        for pattern in DOMAIN_TERM_PATTERNS:
            self.patterns.append(re.compile(pattern))
        if custom_patterns:
            for pattern in custom_patterns:
                self.patterns.append(re.compile(pattern))

    def lock_terms(self, text: str) -> TermLockResult:
        """锁定文本中的术语"""
        locked_terms: Set[str] = set()
        locked_map: dict[str, str] = {}
        protected_text = text

        for pattern in self.patterns:
            for match in pattern.finditer(text):
                term = match.group()
                if term in locked_terms:
                    continue
                locked_terms.add(term)

        # 按位置排序（从后往前替换，避免偏移）
        positions = []
        for term in locked_terms:
            for m in re.finditer(re.escape(term), text):
                positions.append((m.start(), term))

        positions.sort(key=lambda x: x[0], reverse=True)

        for i, (start, term) in enumerate(positions):
            placeholder = f"__TERM_{i}__"
            locked_map[placeholder] = term
            protected_text = protected_text[:start] + placeholder + protected_text[start + len(term):]

        return TermLockResult(
            locked_terms=locked_terms,
            locked_map=locked_map,
            original_text=text,
            protected_text=protected_text,
        )

    def restore_terms(self, protected_text: str, locked_map: dict[str, str]) -> str:
        """恢复术语"""
        restored = protected_text
        for placeholder, term in locked_map.items():
            restored = restored.replace(placeholder, term)
        return restored


class TermLockEngine:
    """
    术语锁定引擎（优化版）

    改进点：
    1. 按长度倒序匹配，防止"长词被短词部分替换"（如：特级装备 vs 装备）
    2. 使用【PROTECTED_TERM_n】占位符，更醒目
    3. 保留语义衔接信息
    """

    def __init__(self, custom_patterns: list[str] | None = None):
        self.patterns: list[str] = list(DOMAIN_TERM_PATTERNS)
        if custom_patterns:
            self.patterns.extend(custom_patterns)

    def lock_terms(self, text: str) -> tuple[str, dict[str, str]]:
        """
        锁定文本中的术语

        Args:
            text: 原始文本

        Returns:
            (保护后的文本, 占位符映射表)
        """
        locked_map: dict[str, str] = {}
        protected_text = text

        # 修正：按长度倒序匹配，防止"长词被短词部分替换"
        sorted_patterns = sorted(self.patterns, key=len, reverse=True)

        for i, pattern in enumerate(sorted_patterns):
            for match in re.finditer(pattern, protected_text):
                term = match.group()
                # 使用更醒目的占位符格式
                placeholder = f"【PROTECTED_TERM_{i}】"
                locked_map[placeholder] = term
                # 替换所有出现的术语
                protected_text = protected_text.replace(term, placeholder)

        return protected_text, locked_map

    def restore_terms(self, rewritten_text: str, locked_map: dict[str, str]) -> str:
        """
        恢复术语（修正：直接根据 Key 替换，不依赖顺序）

        Args:
            rewritten_text: 重写后的文本
            locked_map: 占位符 -> 原始术语的映射

        Returns:
            术语已还原的文本
        """
        restored_text = rewritten_text
        for placeholder, original_term in locked_map.items():
            restored_text = restored_text.replace(placeholder, original_term)
        return restored_text

    def validate_preservation(
        self,
        original_text: str,
        rewritten_text: str,
    ) -> tuple[bool, list[str]]:
        """
        验证术语是否被保留

        Args:
            original_text: 原始文本
            rewritten_text: 重写后的文本

        Returns:
            (是否全部保留, 被破坏的术语列表)
        """
        locked_map = self.lock_terms(original_text)[1]
        original_terms = set(locked_map.values())
        restored_text = self.restore_terms(rewritten_text, locked_map)

        violated_terms = []
        for term in original_terms:
            if term not in restored_text:
                violated_terms.append(term)

        return len(violated_terms) == 0, violated_terms


def extract_terms(text: str) -> Set[str]:
    """提取文本中的所有术语"""
    terms: Set[str] = set()
    for pattern in DOMAIN_TERM_PATTERNS:
        for match in re.finditer(pattern, text):
            terms.add(match.group())
    return terms


def lock_and_restore(original_text: str, rewritten_text: str) -> str:
    """
    快捷函数：锁定 -> 重写 -> 恢复

    Args:
        original_text: 原始文本
        rewritten_text: 重写后的文本（术语已被占位符保护）

    Returns:
        术语已还原的重写文本
    """
    engine = TermLockEngine()
    protected, locked_map = engine.lock_terms(original_text)
    return engine.restore_terms(rewritten_text, locked_map)

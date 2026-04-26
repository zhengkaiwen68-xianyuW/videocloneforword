"""
LLM Provider 工厂

根据配置返回对应的 LLM 供应商实例。
"""

import logging

from ..core.config import config

logger = logging.getLogger(__name__)


def create_llm_provider(provider: str | None = None):
    """
    根据配置创建 LLM Provider 实例

    Args:
        provider: 供应商名称（minimax/openai/claude）。None 时从 config 读取。

    Returns:
        LLMProvider 实例

    Raises:
        ValueError: 不支持的供应商
    """
    provider = provider or getattr(config, 'llm_provider', 'minimax')

    if provider == "minimax":
        from .minimax import MiniMaxAdapter
        return MiniMaxAdapter()
    else:
        raise ValueError(
            f"Unsupported LLM provider: {provider}. "
            f"Supported: minimax"
        )

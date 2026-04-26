"""
LLM Provider Protocol

定义统一的 LLM 调用接口。所有适配器（MiniMax、OpenAI、Claude 等）实现此协议。
使用 Protocol 而非 ABC，更 Pythonic，不需要显式继承。
"""

from typing import Any, Protocol


class LLMProvider(Protocol):
    """LLM 供应商统一接口"""

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """
        生成文本

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            temperature: 温度参数
            max_tokens: 最大 token 数

        Returns:
            生成的文本
        """
        ...

    async def generate_json(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        """
        生成并解析 JSON 输出

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            temperature: 温度参数

        Returns:
            解析后的 JSON 字典
        """
        ...

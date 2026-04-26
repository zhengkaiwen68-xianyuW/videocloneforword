"""
MiniMax API 适配器（向后兼容）

.. deprecated::
    此模块已迁移至 persona_engine.llm.minimax。
    请使用 from persona_engine.llm.minimax import MiniMaxAdapter
"""

from ..llm.minimax import MiniMaxAdapter, extract_json_with_stack  # noqa: F401

__all__ = ["MiniMaxAdapter", "extract_json_with_stack"]

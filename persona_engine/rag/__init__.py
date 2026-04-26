"""
RAG 模块 - 基于向量检索的语料增强

使用 ChromaDB 存储 ASR 转写文本，重写时检索最相似的真实语料作为 few-shot 示例。
"""

from .retriever import RAGRetriever
from .store import ChromaStore

__all__ = ["RAGRetriever", "ChromaStore"]

"""
RAG 检索器

从 ChromaDB 检索相似语料，用于重写时的 few-shot 示例。
"""

import logging
from typing import Any

from ..core.config import RAGConfig
from .store import ChromaStore

logger = logging.getLogger(__name__)


class RAGRetriever:
    """
    RAG 检索器

    功能：
    - 根据输入文本检索最相似的真实语料
    - 按人格过滤，确保风格一致
    - 格式化为 few-shot 示例供 LLM 使用
    """

    def __init__(self, config: RAGConfig):
        """
        初始化检索器

        Args:
            config: RAG 配置
        """
        self.config = config
        self.store = ChromaStore(
            persist_directory=config.chroma_path,
            collection_name=config.collection_name,
        )

    def add_persona_corpus(
        self,
        persona_id: str,
        texts: list[str],
        video_ids: list[str] | None = None,
    ) -> list[str]:
        """
        添加人格语料到向量库

        Args:
            persona_id: 人格 ID
            texts: ASR 转写文本列表
            video_ids: 视频 ID 列表（可选）

        Returns:
            添加的文档 ID 列表
        """
        metadatas = []
        for i, text in enumerate(texts):
            meta = {"persona_id": persona_id}
            if video_ids and i < len(video_ids):
                meta["video_id"] = video_ids[i]
            metadatas.append(meta)

        return self.store.add_documents(
            documents=texts,
            metadatas=metadatas,
        )

    def retrieve_similar(
        self,
        query_text: str,
        persona_id: str | None = None,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        检索相似语料

        Args:
            query_text: 查询文本（原始素材）
            persona_id: 人格 ID（可选，用于过滤）
            top_k: 返回数量（可选，默认使用配置值）

        Returns:
            相似语料列表，按相似度排序
        """
        if not self.config.enabled:
            return []

        top_k = top_k or self.config.top_k
        where = {"persona_id": persona_id} if persona_id else None

        results = self.store.query(
            query_text=query_text,
            n_results=top_k,
            where=where,
        )

        # 过滤低相似度结果
        filtered = [
            r for r in results
            if r["distance"] <= (1 - self.config.similarity_threshold)
        ]

        if filtered:
            logger.info(f"检索到 {len(filtered)} 条相似语料 (阈值: {self.config.similarity_threshold})")
        else:
            logger.info("未检索到满足阈值的相似语料")

        return filtered

    def format_as_few_shot(
        self,
        query_text: str,
        persona_id: str | None = None,
        max_examples: int = 3,
    ) -> str | None:
        """
        检索并格式化为 few-shot 示例

        Args:
            query_text: 查询文本
            persona_id: 人格 ID（可选）
            max_examples: 最大示例数

        Returns:
            格式化的 few-shot 示例文本，无结果时返回 None
        """
        results = self.retrieve_similar(query_text, persona_id, max_examples)

        if not results:
            return None

        examples = []
        for i, r in enumerate(results, 1):
            similarity = 1 - r["distance"]
            examples.append(
                f"### 示例 {i}（相似度: {similarity:.2%}）\n"
                f"{r['document']}"
            )

        return "\n\n".join(examples)

    def get_persona_stats(self, persona_id: str) -> dict[str, Any]:
        """
        获取人格语料统计

        Args:
            persona_id: 人格 ID

        Returns:
            统计信息
        """
        docs = self.store.get_persona_documents(persona_id)
        return {
            "persona_id": persona_id,
            "document_count": len(docs),
            "total_chars": sum(len(d["document"]) for d in docs),
        }

    def delete_persona_corpus(self, persona_id: str) -> int:
        """
        删除人格语料

        Args:
            persona_id: 人格 ID

        Returns:
            删除的文档数量
        """
        return self.store.delete_persona_documents(persona_id)

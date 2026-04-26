"""
ChromaDB 向量存储管理

负责管理 ChromaDB 集合的创建、文档的增删改查。
"""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ChromaStore:
    """
    ChromaDB 向量存储

    功能：
    - 管理 ChromaDB 客户端和集合
    - 添加/删除/查询文档
    - 自动持久化到磁盘
    """

    def __init__(
        self,
        persist_directory: str = "./data/chroma_db",
        collection_name: str = "persona_corpus",
    ):
        """
        初始化 ChromaDB 存储

        Args:
            persist_directory: 持久化目录
            collection_name: 集合名称
        """
        self.persist_directory = persist_directory
        self.collection_name = collection_name
        self._client = None
        self._collection = None

    def _ensure_client(self):
        """懒加载 ChromaDB 客户端"""
        if self._client is None:
            try:
                import chromadb
                from chromadb.config import Settings

                # 确保目录存在
                Path(self.persist_directory).mkdir(parents=True, exist_ok=True)

                self._client = chromadb.PersistentClient(
                    path=self.persist_directory,
                    settings=Settings(anonymized_telemetry=False),
                )
                logger.info(f"ChromaDB 客户端初始化成功: {self.persist_directory}")
            except ImportError:
                raise ImportError(
                    "chromadb 未安装，请运行: pip install chromadb"
                )

        return self._client

    def _ensure_collection(self):
        """懒加载集合"""
        if self._collection is None:
            client = self._ensure_client()
            self._collection = client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},  # 使用余弦相似度
            )
            logger.info(f"集合 '{self.collection_name}' 已就绪，当前文档数: {self._collection.count()}")
        return self._collection

    def add_documents(
        self,
        documents: list[str],
        metadatas: list[dict[str, Any]] | None = None,
        ids: list[str] | None = None,
    ) -> list[str]:
        """
        添加文档到向量库

        Args:
            documents: 文档文本列表
            metadatas: 元数据列表（可选）
            ids: 文档 ID 列表（可选，自动生成）

        Returns:
            添加的文档 ID 列表
        """
        collection = self._ensure_collection()

        # 自动生成 ID
        if ids is None:
            import uuid
            ids = [str(uuid.uuid4()) for _ in documents]

        # 默认元数据
        if metadatas is None:
            metadatas = [{} for _ in documents]

        collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids,
        )
        logger.info(f"添加 {len(documents)} 个文档到集合 '{self.collection_name}'")
        return ids

    def query(
        self,
        query_text: str,
        n_results: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        查询相似文档

        Args:
            query_text: 查询文本
            n_results: 返回结果数量
            where: 过滤条件（可选）

        Returns:
            相似文档列表，每个包含 document, metadata, distance
        """
        collection = self._ensure_collection()

        # 检查集合是否为空
        if collection.count() == 0:
            return []

        query_params = {
            "query_texts": [query_text],
            "n_results": min(n_results, collection.count()),
        }
        if where:
            query_params["where"] = where

        results = collection.query(**query_params)

        # 整理结果
        documents = []
        for i in range(len(results["ids"][0])):
            doc = {
                "id": results["ids"][0][i],
                "document": results["documents"][0][i],
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "distance": results["distances"][0][i] if results["distances"] else 0,
            }
            documents.append(doc)

        return documents

    def delete(self, ids: list[str]) -> None:
        """
        删除文档

        Args:
            ids: 要删除的文档 ID 列表
        """
        collection = self._ensure_collection()
        collection.delete(ids=ids)
        logger.info(f"删除 {len(ids)} 个文档")

    def count(self) -> int:
        """获取文档总数"""
        collection = self._ensure_collection()
        return collection.count()

    def get_persona_documents(self, persona_id: str) -> list[dict[str, Any]]:
        """
        获取指定人格的所有文档

        Args:
            persona_id: 人格 ID

        Returns:
            文档列表
        """
        collection = self._ensure_collection()

        if collection.count() == 0:
            return []

        results = collection.get(
            where={"persona_id": persona_id},
        )

        documents = []
        for i in range(len(results["ids"])):
            doc = {
                "id": results["ids"][i],
                "document": results["documents"][i],
                "metadata": results["metadatas"][i] if results["metadatas"] else {},
            }
            documents.append(doc)

        return documents

    def delete_persona_documents(self, persona_id: str) -> int:
        """
        删除指定人格的所有文档

        Args:
            persona_id: 人格 ID

        Returns:
            删除的文档数量
        """
        collection = self._ensure_collection()

        if collection.count() == 0:
            return 0

        results = collection.get(
            where={"persona_id": persona_id},
        )

        if results["ids"]:
            collection.delete(ids=results["ids"])
            logger.info(f"删除人格 '{persona_id}' 的 {len(results['ids'])} 个文档")
            return len(results["ids"])

        return 0

"""
技法 API 路由

提供技法提炼、查询、推荐的 API 端点。
"""

import asyncio
import logging
import uuid

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .dependencies import persona_repo
from ..storage.persona_repo import TechniqueRepository
from ..technique.topic_analyzer import TopicAnalyzer
from ..technique.hook_deconstructor import HookDeconstructor
from ..technique.structure_mapper import StructureMapper
from ..technique.technique_repo import TechniqueKnowledgeBase
from ..core.types import HookType
from ..core.config import config


logger = logging.getLogger(__name__)
router = APIRouter()

technique_repo = TechniqueRepository()
knowledge_base = TechniqueKnowledgeBase(technique_repo)


def _get_rag_retriever():
    """懒加载 RAG 检索器"""
    try:
        if config.rag.enabled:
            from ..rag.retriever import RAGRetriever
            return RAGRetriever(config.rag)
    except Exception as e:
        logger.warning(f"RAG 检索器初始化失败: {e}")
    return None


# ── Request/Response Models ──

class AnalyzeTechniquesRequest(BaseModel):
    """触发技法提炼请求"""
    pass


class HookAnalysisResponse(BaseModel):
    id: str
    hook_text: str
    hook_type: str
    psychological_mechanism: str
    structural_formula: str
    why_it_works: str
    reconstruction_template: str
    source_video_url: str
    persona_id: str
    created_at: str


class TopicTechniqueResponse(BaseModel):
    angle_patterns: list[str]
    pain_points: list[str]
    topic_formulas: list[str]
    selection_criteria: list[str]
    avoid_patterns: list[str]


class TechniqueSummaryResponse(BaseModel):
    topic_techniques: dict | None
    hook_stats: dict
    structure_count: int


# ── Endpoints ──

@router.post("/personas/{persona_id}/analyze-techniques")
async def analyze_techniques(persona_id: str):
    """
    触发技法提炼

    从人格的 ASR 文本中自动提取选题技法、钩子技法、内容结构。
    """
    try:
        profile = await persona_repo.get_by_id(persona_id)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Persona {persona_id} not found")

    if not profile.source_asr_texts:
        raise HTTPException(status_code=400, detail="Persona has no ASR texts")

    texts = profile.source_asr_texts

    try:
        analyzer = TopicAnalyzer()
        deconstructor = HookDeconstructor()
        mapper = StructureMapper()

        # 并行执行三个分析任务
        topic_task = analyzer.analyze(texts)
        hooks_task = deconstructor.batch_deconstruct(
            hook_texts=[HookDeconstructor.extract_hook_from_text(t) for t in texts],
            full_texts=texts,
            persona_id=persona_id,
        )
        structures_task = mapper.batch_map(
            texts=texts[:3],  # 限制前3个视频避免 token 过多
            persona_id=persona_id,
        )

        topic_result, hooks_result, structures_result = await asyncio.gather(
            topic_task, hooks_task, structures_task
        )

        # 保存到数据库
        await technique_repo.save_topic_technique(topic_result, persona_id)
        for hook in hooks_result:
            hook.id = str(uuid.uuid4())
            await technique_repo.save_hook(hook)
        for struct in structures_result:
            struct.id = str(uuid.uuid4())
            await technique_repo.save_content_structure(struct)

        # 更新人格画像中的技法字段
        await persona_repo.update(persona_id, {
            "topic_techniques": topic_result.to_dict(),
            "hook_techniques": [h.to_dict() for h in hooks_result],
            "structure_patterns": [s.to_dict() for s in structures_result],
        })

        return {
            "persona_id": persona_id,
            "topic_techniques": topic_result.to_dict(),
            "hooks_count": len(hooks_result),
            "structures_count": len(structures_result),
            "status": "completed",
        }

    except Exception as e:
        logger.error(f"Technique analysis failed: {e}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@router.get("/personas/{persona_id}/techniques")
async def get_persona_techniques(persona_id: str):
    """获取人格的技法画像"""
    try:
        summary = await knowledge_base.get_persona_techniques_summary(persona_id)
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hooks")
async def list_hooks(
    persona_id: str = Query(None, description="按人格 ID 筛选"),
    hook_type: str = Query(None, description="按钩子类型筛选"),
    query: str = Query("", description="关键词搜索"),
    limit: int = Query(20, ge=1, le=100),
):
    """查询技法库"""
    try:
        if persona_id:
            hooks = await technique_repo.get_hooks_by_persona(persona_id)
        elif hook_type:
            hooks = await technique_repo.get_hooks_by_type(hook_type)
        elif query:
            hooks = await technique_repo.search_hooks(query, limit=limit)
        else:
            hooks = await technique_repo.search_hooks("", limit=limit)

        return {
            "hooks": [h.to_dict() for h in hooks[:limit]],
            "total": len(hooks),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hooks/{hook_id}")
async def get_hook(hook_id: str):
    """获取单个钩子分析"""
    hook = await technique_repo.get_hook_by_id(hook_id)
    if not hook:
        raise HTTPException(status_code=404, detail="Hook not found")
    return hook.to_dict()


@router.delete("/hooks/{hook_id}")
async def delete_hook(hook_id: str):
    """删除钩子分析"""
    deleted = await technique_repo.delete_hook(hook_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Hook not found")
    return {"status": "deleted", "id": hook_id}


@router.get("/personas/{persona_id}/hook-stats")
async def get_hook_stats(persona_id: str):
    """获取人格的钩子技法统计"""
    try:
        stats = await knowledge_base.get_hook_stats(persona_id)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── RAG 语料管理 API ──

class AddCorpusRequest(BaseModel):
    """添加语料请求"""
    texts: list[str] = Field(..., description="ASR 转写文本列表")
    video_ids: list[str] = Field(default_factory=list, description="视频 ID 列表（可选）")


class SearchRequest(BaseModel):
    """检索请求"""
    query: str = Field(..., description="查询文本")
    persona_id: str = Field(default="", description="人格 ID（可选，用于过滤）")
    top_k: int = Field(default=5, ge=1, le=20, description="返回数量")


@router.post("/personas/{persona_id}/rag/corpus")
async def add_persona_corpus(persona_id: str, request: AddCorpusRequest):
    """
    添加人格语料到 RAG 知识库

    将 ASR 转写文本添加到向量库，用于后续检索相似语料。
    """
    rag_retriever = _get_rag_retriever()
    if not rag_retriever:
        raise HTTPException(status_code=503, detail="RAG 服务未启用")

    try:
        ids = rag_retriever.add_persona_corpus(
            persona_id=persona_id,
            texts=request.texts,
            video_ids=request.video_ids if request.video_ids else None,
        )
        return {
            "persona_id": persona_id,
            "added_count": len(ids),
            "ids": ids,
        }
    except Exception as e:
        logger.error(f"添加语料失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/personas/{persona_id}/rag/stats")
async def get_rag_stats(persona_id: str):
    """
    获取人格的 RAG 语料统计

    返回语料数量、总字符数等统计信息。
    """
    rag_retriever = _get_rag_retriever()
    if not rag_retriever:
        raise HTTPException(status_code=503, detail="RAG 服务未启用")

    try:
        stats = rag_retriever.get_persona_stats(persona_id)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/personas/{persona_id}/rag/corpus")
async def delete_persona_corpus(persona_id: str):
    """
    删除人格的 RAG 语料

    删除指定人格的所有向量化语料。
    """
    rag_retriever = _get_rag_retriever()
    if not rag_retriever:
        raise HTTPException(status_code=503, detail="RAG 服务未启用")

    try:
        deleted_count = rag_retriever.delete_persona_corpus(persona_id)
        return {
            "persona_id": persona_id,
            "deleted_count": deleted_count,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rag/search")
async def search_similar_corpus(request: SearchRequest):
    """
    检索相似语料

    根据查询文本检索最相似的真实语料。
    """
    rag_retriever = _get_rag_retriever()
    if not rag_retriever:
        raise HTTPException(status_code=503, detail="RAG 服务未启用")

    try:
        results = rag_retriever.retrieve_similar(
            query_text=request.query,
            persona_id=request.persona_id if request.persona_id else None,
            top_k=request.top_k,
        )
        return {
            "query": request.query,
            "results": results,
            "count": len(results),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

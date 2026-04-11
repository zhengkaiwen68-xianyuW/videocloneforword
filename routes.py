"""
FastAPI 路由

提供本地 API 接口供 .exe 调用
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from persona_engine.core.exceptions import (
    PersonaNotFoundError,
    TaskNotFoundError,
    ValidationError,
    PersonaEngineException,
    BilibiliDownloadError,
    TranscriptionError,
)
from persona_engine.core.types import (
    TaskStatus,
    PersonaCreateRequest,
    PersonaUpdateRequest,
    PersonaAddVideosRequest,
    RewriteRequest,
    BatchRewriteRequest,
    PersonalityProfile,
    LogicArchitecture,
    TemporalPattern,
    DeepPsychology,
)
from persona_engine.core.task_registry import task_registry
from persona_engine.storage.persona_repo import PersonaRepository, TaskRepository
from persona_engine.asr.personality_extractor import PersonalityExtractor


logger = logging.getLogger(__name__)

# 路由实例
router = APIRouter()

# 仓储实例
persona_repo = PersonaRepository()
task_repo = TaskRepository()


# ========== 请求/响应模型 ==========

class PersonaResponse(BaseModel):
    """人格响应"""
    id: str
    name: str
    verbal_tics: list[str]
    grammar_prefs: list[str]
    logic_architecture: dict
    temporal_patterns: dict
    raw_json: dict
    created_at: str
    updated_at: str


class PersonaListResponse(BaseModel):
    """人格列表响应"""
    personas: list[PersonaResponse]
    total: int


class PersonaCreateResponse(BaseModel):
    """创建人格响应"""
    id: str
    name: str
    message: str


class RewriteRequestModel(BaseModel):
    """重写请求模型"""
    source_text: str = Field(..., min_length=1, description="原始素材文本")
    persona_ids: list[str] = Field(..., min_length=1, description="目标人格 ID 列表")
    locked_terms: list[str] = Field(default_factory=list, description="术语锚点")
    max_iterations: int = Field(default=5, ge=1, le=10, description="最大迭代次数")
    timeout_seconds: int = Field(default=300, ge=60, le=600, description="超时时间")


class BatchRewriteRequestModel(BaseModel):
    """批量洗稿请求模型"""
    source_texts: list[str] = Field(..., min_length=1, description="原始素材列表")
    persona_ids: list[str] = Field(..., min_length=1, description="人格 ID 列表")
    locked_terms: list[str] = Field(default_factory=list, description="术语锚点")
    max_iterations: int = Field(default=5, ge=1, le=10)
    timeout_seconds: int = Field(default=300, ge=60, le=600)


class TaskStatusResponse(BaseModel):
    """任务状态响应"""
    task_id: str
    status: str
    iteration: int
    current_score: float
    best_score: float
    best_text: str
    history_count: int
    elapsed_seconds: float


class BatchRewriteResponse(BaseModel):
    """批量洗稿响应"""
    batch_id: str
    task_ids: list[str]
    total_count: int


class ErrorResponse(BaseModel):
    """错误响应"""
    error: str
    message: str
    code: str | None = None


class BilibiliASRRequest(BaseModel):
    """B站视频ASR请求"""
    # 支持两种格式：
    # 1. 单个URL: url="https://..."
    # 2. 多行URL: urls=["url1", "url2", ...] 或 urls="url1\nurl2\nurl3"
    url: str | None = Field(None, description="单个B站视频链接")
    urls: list[str] | None = Field(None, description="多个B站视频链接列表")
    name: str | None = Field(None, description="可选的名称，用于创建人格")


class BilibiliASRResponse(BaseModel):
    """B站视频ASR响应"""
    task_id: str
    status: str
    total_videos: int = 0
    completed_videos: int = 0
    message: str


# ========== 人格管理路由 ==========

@router.get("/personas", response_model=PersonaListResponse)
async def get_personas():
    """
    GET /v1/personas

    获取已存储的人格清单
    """
    try:
        personas = await persona_repo.get_all()
        return PersonaListResponse(
            personas=[
                PersonaResponse(
                    id=p.id,
                    name=p.name,
                    verbal_tics=p.verbal_tics,
                    grammar_prefs=p.grammar_prefs,
                    logic_architecture={
                        "opening_style": p.logic_architecture.opening_style,
                        "transition_patterns": p.logic_architecture.transition_patterns,
                        "closing_style": p.logic_architecture.closing_style,
                        "topic_organization": p.logic_architecture.topic_organization,
                    },
                    temporal_patterns={
                        "avg_pause_duration": p.temporal_patterns.avg_pause_duration,
                        "pause_frequency": p.temporal_patterns.pause_frequency,
                        "speech_rhythm": p.temporal_patterns.speech_rhythm,
                        "excitement_curve": p.temporal_patterns.excitement_curve,
                    },
                    raw_json=p.raw_json,
                    created_at=p.created_at.isoformat(),
                    updated_at=p.updated_at.isoformat(),
                )
                for p in personas
            ],
            total=len(personas),
        )
    except PersonaEngineException as e:
        raise HTTPException(status_code=500, detail=e.to_dict())


@router.post("/personas", response_model=PersonaCreateResponse)
async def create_persona(request: PersonaCreateRequest):
    """
    POST /v1/personas

    创建新人格（上传 ASR 文本或视频链接进行人格孵化）
    """
    try:
        # 检查参数：source_texts 和 video_urls 至少要有一个
        has_texts = request.source_texts and len(request.source_texts) > 0
        has_videos = request.video_urls and len(request.video_urls) > 0

        if not has_texts and not has_videos:
            raise ValidationError(
                message="Either source_texts or video_urls is required",
                field="source_texts/video_urls",
            )

        # 如果提供了视频链接，使用后台任务
        if has_videos and not has_texts:
            persona_id = str(uuid.uuid4())[:8]
            task_id = f"persona_{persona_id}"

            # 先创建待处理的人格记录
            profile = PersonalityProfile(
                id=persona_id,
                name=request.name,
                verbal_tics=[],
                grammar_prefs=[],
                logic_architecture=LogicArchitecture(
                    opening_style="待分析",
                    transition_patterns=[],
                    closing_style="待分析",
                    topic_organization="待分析",
                ),
                temporal_patterns=TemporalPattern(
                    avg_pause_duration=0.5,
                    pause_frequency=1.0,
                    speech_rhythm="medium",
                    excitement_curve=[],
                ),
                deep_psychology=DeepPsychology(),
                raw_json={"status": "processing", "task_id": task_id},
                source_asr_texts=[],
            )
            await persona_repo.create(profile)

            # 启动后台任务：从视频提取ASR并计算人格
            # 使用 asyncio.create_task + task_registry 进行追踪，以便 shutdown 时取消
            logger.info(f"Creating task {task_id} for persona {persona_id} with {len(request.video_urls)} videos")
            task = asyncio.create_task(
                _run_persona_from_videos_task_with_tracking(
                    task_id=task_id,
                    persona_id=persona_id,
                    video_urls=request.video_urls,
                )
            )
            logger.info(f"Task {task_id} created, registered: {task_registry.list_tasks()}")
            task_registry.register(task_id, task)
            task.add_done_callback(lambda t: task_registry.unregister(task_id))
            logger.info(f"Task {task_id} fully registered, done={task.done()}")

            return PersonaCreateResponse(
                id=persona_id,
                name=request.name,
                message="Persona created, processing videos in background",
            )

        # 如果提供了 ASR 文本，直接生成人格
        extractor = PersonalityExtractor()
        profile = extractor.extract(
            texts=request.source_texts,
            author_name=request.name,
        )

        # 保存到数据库
        await persona_repo.create(profile)

        return PersonaCreateResponse(
            id=profile.id,
            name=profile.name,
            message="Persona created successfully",
        )

    except ValidationError as e:
        raise HTTPException(status_code=400, detail=e.to_dict())
    except PersonaEngineException as e:
        raise HTTPException(status_code=500, detail=e.to_dict())


@router.post("/personas/{persona_id}/videos")
async def add_videos_to_persona(
    persona_id: str,
    request: PersonaAddVideosRequest,
):
    """
    POST /v1/personas/{id}/videos

    向已有人格追加视频链接，自动提取ASR并重新计算人格
    """
    try:
        # 检查人格是否存在
        persona = await persona_repo.get_by_id(persona_id)
        if not persona:
            raise PersonaNotFoundError(persona_id)

        # 启动后台任务：追加视频并重新计算人格
        task_id = f"persona_upgrade_{persona_id}"

        task = asyncio.create_task(
            _run_persona_upgrade_task_with_tracking(
                task_id=task_id,
                persona_id=persona_id,
                video_urls=request.video_urls,
            )
        )
        task_registry.register(task_id, task)
        task.add_done_callback(lambda t: task_registry.unregister(task_id))

        return {
            "persona_id": persona_id,
            "task_id": task_id,
            "message": f"Processing {len(request.video_urls)} videos, persona will be upgraded automatically",
        }

    except PersonaNotFoundError as e:
        raise HTTPException(status_code=404, detail={"error": "NotFound", "message": str(e)})
    except PersonaEngineException as e:
        raise HTTPException(status_code=500, detail={"error": "InternalError", "message": str(e)})


@router.get("/personas/{persona_id}", response_model=PersonaResponse)
async def get_persona(persona_id: str):
    """
    GET /v1/personas/{id}

    获取指定人格详情
    """
    try:
        persona = await persona_repo.get_by_id(persona_id)
        return PersonaResponse(
            id=persona.id,
            name=persona.name,
            verbal_tics=persona.verbal_tics,
            grammar_prefs=persona.grammar_prefs,
            logic_architecture={
                "opening_style": persona.logic_architecture.opening_style,
                "transition_patterns": persona.logic_architecture.transition_patterns,
                "closing_style": persona.logic_architecture.closing_style,
                "topic_organization": persona.logic_architecture.topic_organization,
            },
            temporal_patterns={
                "avg_pause_duration": persona.temporal_patterns.avg_pause_duration,
                "pause_frequency": persona.temporal_patterns.pause_frequency,
                "speech_rhythm": persona.temporal_patterns.speech_rhythm,
                "excitement_curve": persona.temporal_patterns.excitement_curve,
            },
            raw_json=persona.raw_json,
            created_at=persona.created_at.isoformat(),
            updated_at=persona.updated_at.isoformat(),
        )

    except PersonaNotFoundError:
        raise HTTPException(status_code=404, detail={"error": "Persona not found", "persona_id": persona_id})
    except PersonaEngineException as e:
        raise HTTPException(status_code=500, detail=e.to_dict())


@router.put("/personas/{persona_id}", response_model=PersonaResponse)
async def update_persona(persona_id: str, request: PersonaUpdateRequest):
    """
    PUT /v1/personas/{id}

    更新人格（支持手动编辑）
    """
    try:
        updates = {}

        if request.verbal_tics is not None:
            updates["verbal_tics"] = request.verbal_tics
        if request.grammar_prefs is not None:
            updates["grammar_prefs"] = request.grammar_prefs
        if request.logic_architecture is not None:
            updates["logic_architecture"] = {
                "opening_style": request.logic_architecture.opening_style,
                "transition_patterns": request.logic_architecture.transition_patterns,
                "closing_style": request.logic_architecture.closing_style,
                "topic_organization": request.logic_architecture.topic_organization,
            }
        if request.temporal_patterns is not None:
            updates["temporal_patterns"] = {
                "avg_pause_duration": request.temporal_patterns.avg_pause_duration,
                "pause_frequency": request.temporal_patterns.pause_frequency,
                "speech_rhythm": request.temporal_patterns.speech_rhythm,
                "excitement_curve": request.temporal_patterns.excitement_curve,
            }

        persona = await persona_repo.update(persona_id, updates)

        return PersonaResponse(
            id=persona.id,
            name=persona.name,
            verbal_tics=persona.verbal_tics,
            grammar_prefs=persona.grammar_prefs,
            logic_architecture={
                "opening_style": persona.logic_architecture.opening_style,
                "transition_patterns": persona.logic_architecture.transition_patterns,
                "closing_style": persona.logic_architecture.closing_style,
                "topic_organization": persona.logic_architecture.topic_organization,
            },
            temporal_patterns={
                "avg_pause_duration": persona.temporal_patterns.avg_pause_duration,
                "pause_frequency": persona.temporal_patterns.pause_frequency,
                "speech_rhythm": persona.temporal_patterns.speech_rhythm,
                "excitement_curve": persona.temporal_patterns.excitement_curve,
            },
            raw_json=persona.raw_json,
            created_at=persona.created_at.isoformat(),
            updated_at=persona.updated_at.isoformat(),
        )

    except PersonaNotFoundError:
        raise HTTPException(status_code=404, detail={"error": "Persona not found", "persona_id": persona_id})
    except PersonaEngineException as e:
        raise HTTPException(status_code=500, detail=e.to_dict())


@router.delete("/personas/{persona_id}")
async def delete_persona(persona_id: str):
    """
    DELETE /v1/personas/{id}

    删除人格
    """
    try:
        await persona_repo.delete(persona_id)
        return {"message": "Persona deleted", "persona_id": persona_id}

    except PersonaNotFoundError:
        raise HTTPException(status_code=404, detail={"error": "Persona not found", "persona_id": persona_id})
    except PersonaEngineException as e:
        raise HTTPException(status_code=500, detail=e.to_dict())


# ========== 重写任务路由 ==========

@router.post("/process/batch", response_model=dict)
async def batch_rewrite(request: BatchRewriteRequestModel):
    """
    POST /v1/process/batch

    发起批量洗稿请求
    """
    try:
        batch_id = str(uuid.uuid4())[:8]
        task_ids = []

        # 为每条素材创建任务
        for source_text in request.source_texts:
            task_id = str(uuid.uuid4())[:8]

            # 创建任务记录
            await task_repo.create(
                task_id=task_id,
                source_text=source_text,
                persona_ids=request.persona_ids,
                locked_terms=request.locked_terms,
            )

            # 将重写任务添加到后台（使用task_registry追踪）
            task = asyncio.create_task(
                run_rewrite_task(
                    task_id=task_id,
                    source_text=source_text,
                    persona_ids=request.persona_ids,
                    locked_terms=request.locked_terms,
                    max_iterations=request.max_iterations,
                    timeout_seconds=request.timeout_seconds,
                )
            )
            task_registry.register(task_id, task)
            task.add_done_callback(lambda t: task_registry.unregister(task_id))

            task_ids.append(task_id)

        return {
            "batch_id": batch_id,
            "task_ids": task_ids,
            "total_count": len(task_ids),
        }

    except PersonaEngineException as e:
        raise HTTPException(status_code=500, detail=e.to_dict())


async def run_rewrite_task(
    task_id: str,
    source_text: str,
    persona_ids: list[str],
    locked_terms: list[str],
    max_iterations: int,
    timeout_seconds: int,
):
    """
    后台执行重写任务

    完整流程：人格注入 → MiniMax 重写 → 审计评分 → 迭代优化
    """
    from persona_engine.rewrite.minimax_adapter import MiniMaxAdapter
    from persona_engine.rewrite.persona_injector import PersonaInjector
    from persona_engine.audit.reverse_agent import ReverseAgent
    from persona_engine.audit.scorer import ConsistencyScorer
    from persona_engine.audit.iteration_controller import IterationController

    try:
        # 获取人格画像
        personas = await persona_repo.get_by_ids(persona_ids)
        if not personas:
            await task_repo.complete(task_id, status="failed", error_message="No personas found")
            return

        # 初始化组件
        minimax = MiniMaxAdapter()
        injector = PersonaInjector(minimax)
        reverse_agent = ReverseAgent(minimax)
        scorer = ConsistencyScorer(reverse_agent)
        controller = IterationController(
            task_id=task_id,
            max_iterations=max_iterations,
            timeout_seconds=timeout_seconds,
        )

        controller.start()

        # 迭代重写
        while controller.should_continue():
            # 人格注入重写
            result = await injector.inject(
                source_text=source_text,
                persona_profile=personas[0],  # 目前单人格
                locked_terms=locked_terms,
            )

            rewritten_text = result["rewritten_text"]

            # 评分
            score_result = await scorer.score(
                rewritten_text=rewritten_text,
                original_profile=personas[0],
                locked_terms=locked_terms,
            )

            # ========== 术语硬熔断处理 ==========
            # 如果术语保护失败，不记录此版本，立即触发重写
            if score_result.get("status") == "FAIL_TERM_PROTECTION":
                logger.warning(
                    f"Task {task_id}: 术语保护失败 ({score_result.get('reason')})，立即重写"
                )
                # 记录失败信息但不参与评分比较
                await task_repo.update_result(
                    task_id=task_id,
                    best_text="[术语保护失败]",
                    best_score=0.0,
                    best_iteration=controller.state.iteration + 1,
                    history_versions=[{
                        "status": "FAIL_TERM_PROTECTION",
                        "reason": score_result.get("reason"),
                        "iteration": controller.state.iteration + 1,
                    }],
                    status="running",
                )
                continue  # 不调用 evaluate_and_record，直接进入下一轮

            current_score = score_result["total_score"]

            # 评估并记录（只有通过术语硬检查才进入此处）
            await controller.evaluate_and_record(
                rewritten_text=rewritten_text,
                score=current_score,
                metadata=score_result,
            )

            # 更新任务进度
            history_data = [
                {
                    "version": v.version,
                    "score": v.consistency_score,
                    "iteration": v.iteration,
                }
                for v in controller.state.history
            ]
            await task_repo.update_result(
                task_id=task_id,
                best_text=controller.state.best_text,
                best_score=controller.state.best_score,
                best_iteration=controller.state.best_iteration,
                history_versions=history_data,
                status="running",
            )

        # 完成任务
        best = controller.get_best_result()
        await task_repo.complete(
            task_id=task_id,
            status="completed" if best["score"] >= 90 else "completed_below_threshold",
        )

        logger.info(f"Task {task_id} completed with score {best['score']:.2f}")

    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}")
        await task_repo.complete(task_id, status="failed", error_message=str(e))


@router.get("/tasks/{task_id}/status", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """
    GET /v1/tasks/{id}/status

    查询重写迭代进度与当前最高分
    """
    try:
        status = await task_repo.get_status(task_id)

        return TaskStatusResponse(
            task_id=status["task_id"],
            status=status["status"],
            iteration=status.get("best_iteration", 0),
            current_score=status["best_score"],
            best_score=status["best_score"],
            best_text=status["best_text"],
            history_count=status["history_count"],
            elapsed_seconds=0.0,  # 简化处理
        )

    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail={"error": "Task not found", "task_id": task_id})
    except PersonaEngineException as e:
        raise HTTPException(status_code=500, detail=e.to_dict())


@router.post("/asr/from-url", response_model=BilibiliASRResponse)
async def bilibili_asr(request: BilibiliASRRequest):
    """
    POST /v1/asr/from-url

    输入B站视频链接，自动下载并提取ASR文本
    支持单条或多条链接（多行）
    """
    from persona_engine.asr.bilibili_downloader import (
        BilibiliDownloader,
        is_valid_bilibili_url,
        parse_multiple_urls,
        VIDEO_SPLIT_MARKER,
    )

    try:
        # 解析URL列表
        urls = []

        if request.urls:
            # 直接使用urls列表
            for u in request.urls:
                if isinstance(u, str):
                    parsed = parse_multiple_urls(u)
                    urls.extend(parsed)
                else:
                    urls.append(str(u))
        elif request.url:
            # 单个URL，检查是否包含多行
            parsed = parse_multiple_urls(request.url)
            urls = parsed

        if not urls:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "InvalidBilibiliURL",
                    "message": "未提供有效的B站视频链接",
                    "code": "INVALID_URL",
                },
            )

        task_id = f"bili_{str(uuid.uuid4())[:8]}"

        # 在后台执行批量下载和ASR（使用task_registry追踪）
        task = asyncio.create_task(
            run_bilibili_asr_task(
                task_id=task_id,
                urls=urls,
                name=request.name,
            )
        )
        task_registry.register(task_id, task)
        task.add_done_callback(lambda t: task_registry.unregister(task_id))

        return BilibiliASRResponse(
            task_id=task_id,
            status="processing",
            total_videos=len(urls),
            completed_videos=0,
            message=f"正在处理 {len(urls)} 个视频，请稍候...",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bilibili ASR request failed: {e}")
        raise HTTPException(status_code=500, detail={"error": "InternalError", "message": str(e)})


async def run_bilibili_asr_task(task_id: str, urls: list[str], name: str | None):
    """
    后台执行B站视频批量下载和ASR

    Args:
        task_id: 任务ID
        urls: B站视频链接列表
        name: 可选的名称
    """
    from persona_engine.asr.bilibili_downloader import (
        BilibiliDownloader,
        VIDEO_SPLIT_MARKER,
    )
    from persona_engine.asr.transcriber import WhisperTranscriber
    from persona_engine.storage.persona_repo import TaskRepository

    task_repo = TaskRepository()
    downloader = BilibiliDownloader()
    transcriber = WhisperTranscriber()
    audio_paths = []

    all_results = []  # 存储所有视频的ASR结果
    completed = 0
    failed = 0

    try:
        total = len(urls)

        # 先创建任务记录
        await task_repo.create(
            task_id=task_id,
            source_text=f"[ASR Task] Processing {total} videos: {', '.join(urls[:3])}{'...' if len(urls) > 3 else ''}",
            persona_ids=[],
            locked_terms=[],
        )

        # 更新任务状态
        await task_repo.update_result(
            task_id=task_id,
            best_text="",
            best_score=0.0,
            best_iteration=0,
            history_versions=[{
                "status": "processing",
                "total": total,
                "completed": 0,
                "failed": 0,
            }],
            status="running",
        )

        # 逐个处理视频
        for i, url in enumerate(urls):
            try:
                # 更新当前进度
                await task_repo.update_result(
                    task_id=task_id,
                    best_text="",
                    best_score=0.0,
                    best_iteration=0,
                    history_versions=[{
                        "status": f"processing ({i+1}/{total})",
                        "url": url,
                        "phase": "downloading",
                        "progress": (i / total) * 100,
                    }],
                    status="running",
                )

                # 下载视频并提取音频
                def progress_callback(progress: float, status: str):
                    logger.info(f"Task {task_id} [{i+1}/{total}]: {status}")

                audio_path = await downloader.download_and_extract_audio(url, progress_callback)
                audio_paths.append(audio_path)

                # 更新为转写中
                await task_repo.update_result(
                    task_id=task_id,
                    best_text="",
                    best_score=0.0,
                    best_iteration=0,
                    history_versions=[{
                        "status": f"processing ({i+1}/{total})",
                        "url": url,
                        "phase": "transcribing",
                        "progress": (i / total) * 100 + 50 / total,
                    }],
                    status="running",
                )

                # 执行ASR转写
                asr_result = transcriber.transcribe(audio_path)

                # 保存单个视频结果（带视频索引标识）
                video_result = {
                    "index": i,
                    "url": url,
                    "text": asr_result.text,
                    "wpm": asr_result.wpm,
                    "duration": asr_result.total_duration,
                    "word_count": len(asr_result.words),
                }
                all_results.append(video_result)

                completed += 1
                logger.info(f"Task {task_id} [{i+1}/{total}] completed: {len(asr_result.text)} chars")

            except Exception as e:
                failed += 1
                logger.error(f"Task {task_id} [{i+1}/{total}] failed: {e}")
                all_results.append({
                    "index": i,
                    "url": url,
                    "error": str(e),
                })

        # 构建最终结果文本，使用分割标记区分不同视频
        # 这样在创建人格时可以正确分割
        final_texts = []
        for result in all_results:
            if "text" in result:
                final_texts.append(result["text"])

        # 用特殊标记连接多个视频的ASR结果
        combined_text = VIDEO_SPLIT_MARKER.join(final_texts)

        await task_repo.update_result(
            task_id=task_id,
            best_text=combined_text,
            best_score=0.0,
            best_iteration=0,
            history_versions=[{
                "status": "completed",
                "total": total,
                "completed": completed,
                "failed": failed,
                "results": [
                    {"index": r.get("index"), "url": r.get("url"), "text_len": len(r.get("text", ""))}
                    for r in all_results
                ],
            }],
            status="completed",
        )

        logger.info(f"Task {task_id} batch completed: {completed}/{total} successful")

    except Exception as e:
        logger.error(f"Task {task_id} batch failed: {e}")
        await task_repo.update_result(
            task_id=task_id,
            best_text="",
            best_score=0.0,
            best_iteration=0,
            history_versions=[{"status": "failed", "error": str(e)}],
            status="failed",
        )
    finally:
        # 清理临时文件
        for audio_path in audio_paths:
            try:
                downloader.cleanup(audio_path)
            except Exception:
                pass
        transcriber.release()


async def _run_persona_from_videos_task_with_tracking(
    task_id: str,
    persona_id: str,
    video_urls: list[str],
):
    """
    后台任务包装器：追踪任务执行并在完成后自动取消注册

    Args:
        task_id: 任务ID
        persona_id: 人格ID
        video_urls: 视频链接列表
    """
    try:
        await run_persona_from_videos_task(
            task_id=task_id,
            persona_id=persona_id,
            video_urls=video_urls,
        )
    except Exception as e:
        logger.error(f"Task {task_id} failed with exception: {e}", exc_info=True)
    finally:
        # 确保任务从注册表中移除
        task_registry.unregister(task_id)


async def _update_persona_progress(persona_id: str, completed: int, total: int):
    """
    更新人格进度到数据库

    Args:
        persona_id: 人格ID
        completed: 已完成视频数
        total: 视频总数
    """
    try:
        raw_json = {
            "status": "processing",
            "task_id": f"persona_{persona_id}",
            "progress": f"{completed}/{total}",
            "completed_videos": completed,
            "total_videos": total,
        }
        await persona_repo.update(persona_id, {"raw_json": raw_json})
    except Exception as e:
        logger.warning(f"Failed to update persona progress: {e}")


async def run_persona_from_videos_task(
    task_id: str,
    persona_id: str,
    video_urls: list[str],
):
    """
    后台任务：从视频创建新人格

    Args:
        task_id: 任务ID
        persona_id: 人格ID
        video_urls: 视频链接列表
    """
    from persona_engine.asr.bilibili_downloader import (
        BilibiliDownloader,
        VIDEO_SPLIT_MARKER,
    )
    from persona_engine.asr.transcriber import WhisperTranscriber

    downloader = BilibiliDownloader()
    transcriber = WhisperTranscriber()
    audio_paths = []
    all_results = []
    completed = 0
    failed = 0

    try:
        total = len(video_urls)
        logger.info(f"Task {task_id}: Starting persona creation from {total} videos")

        # 逐个处理视频（每个视频有超时保护）
        VIDEO_TIMEOUT_SECONDS = 300  # 5分钟超时

        for i, url in enumerate(video_urls):
            try:
                logger.info(f"Task {task_id} [{i+1}/{total}]: Downloading {url}")

                # 下载视频并提取音频（带超时保护）
                audio_path = await asyncio.wait_for(
                    downloader.download_and_extract_audio(url),
                    timeout=VIDEO_TIMEOUT_SECONDS,
                )
                audio_paths.append(audio_path)

                # 执行ASR转写（带超时保护）
                asr_result = await asyncio.wait_for(
                    asyncio.to_thread(transcriber.transcribe, audio_path),
                    timeout=VIDEO_TIMEOUT_SECONDS,
                )

                all_results.append({
                    "index": i,
                    "url": url,
                    "text": asr_result.text,
                })
                completed += 1
                logger.info(f"Task {task_id} [{i+1}/{total}]: Transcribed {len(asr_result.text)} chars")

                # 定期更新数据库进度（每3个视频或完成时）
                if completed % 3 == 0 or completed == total:
                    await _update_persona_progress(persona_id, completed, total)

            except asyncio.TimeoutError:
                failed += 1
                logger.error(f"Task {task_id} [{i+1}/{total}] timed out after {VIDEO_TIMEOUT_SECONDS}s")
                all_results.append({
                    "index": i,
                    "url": url,
                    "error": f"Timeout after {VIDEO_TIMEOUT_SECONDS}s",
                })
            except Exception as e:
                failed += 1
                logger.error(f"Task {task_id} [{i+1}/{total}] failed: {e}")
                all_results.append({
                    "index": i,
                    "url": url,
                    "error": str(e),
                })

        # 构建ASR文本
        final_texts = [r["text"] for r in all_results if "text" in r]
        combined_text = VIDEO_SPLIT_MARKER.join(final_texts)

        if not final_texts:
            logger.error(f"Task {task_id}: No successful transcriptions")
            return

        # 使用人格提取器生成画像
        extractor = PersonalityExtractor()
        profile = extractor.extract(
            texts=final_texts,
            author_name=None,  # 保持原有名称
        )

        # 构建更新字典（与数据库字段对应）
        updates = {
            "name": profile.name,
            "verbal_tics": profile.verbal_tics,
            "grammar_prefs": profile.grammar_prefs,
            "logic_architecture": {
                "opening_style": profile.logic_architecture.opening_style,
                "transition_patterns": profile.logic_architecture.transition_patterns,
                "closing_style": profile.logic_architecture.closing_style,
                "topic_organization": profile.logic_architecture.topic_organization,
            },
            "temporal_patterns": {
                "avg_pause_duration": profile.temporal_patterns.avg_pause_duration,
                "pause_frequency": profile.temporal_patterns.pause_frequency,
                "speech_rhythm": profile.temporal_patterns.speech_rhythm,
                "excitement_curve": profile.temporal_patterns.excitement_curve,
            },
            "raw_json": {
                "status": "completed",
                "task_id": task_id,
                "source_video_count": total,
                "successful_count": completed,
                "failed_count": failed,
            },
            "source_asr_texts": final_texts,
        }

        await persona_repo.update(persona_id, updates)
        logger.info(f"Task {task_id}: Persona {persona_id} created successfully")

    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}")
    finally:
        # 清理临时文件
        for audio_path in audio_paths:
            try:
                downloader.cleanup(audio_path)
            except Exception:
                pass
        transcriber.release()


async def _run_persona_upgrade_task_with_tracking(
    task_id: str,
    persona_id: str,
    video_urls: list[str],
):
    """
    后台任务包装器：追踪任务执行并在完成后自动取消注册

    Args:
        task_id: 任务ID
        persona_id: 人格ID
        video_urls: 视频链接列表
    """
    try:
        await run_persona_upgrade_task(
            task_id=task_id,
            persona_id=persona_id,
            video_urls=video_urls,
        )
    except Exception as e:
        logger.error(f"Task {task_id} failed with exception: {e}", exc_info=True)
    finally:
        # 确保任务从注册表中移除
        task_registry.unregister(task_id)


async def run_persona_upgrade_task(
    task_id: str,
    persona_id: str,
    video_urls: list[str],
):
    """
    后台任务：追加视频到已有人格并重新计算

    Args:
        task_id: 任务ID
        persona_id: 人格ID
        video_urls: 视频链接列表
    """
    from persona_engine.asr.bilibili_downloader import (
        BilibiliDownloader,
        VIDEO_SPLIT_MARKER,
    )
    from persona_engine.asr.transcriber import WhisperTranscriber

    downloader = BilibiliDownloader()
    transcriber = WhisperTranscriber()
    audio_paths = []
    all_results = []
    completed = 0
    failed = 0

    try:
        total = len(video_urls)
        logger.info(f"Task {task_id}: Starting persona upgrade for {persona_id} with {total} videos")

        # 获取现有的人格数据
        existing_persona = await persona_repo.get_by_id(persona_id)
        if not existing_persona:
            logger.error(f"Task {task_id}: Persona {persona_id} not found")
            return

        existing_texts = existing_persona.source_asr_texts or []
        logger.info(f"Task {task_id}: Existing texts: {len(existing_texts)} videos")

        # 逐个处理新视频
        for i, url in enumerate(video_urls):
            try:
                logger.info(f"Task {task_id} [{i+1}/{total}]: Downloading {url}")

                # 下载视频并提取音频
                audio_path = await downloader.download_and_extract_audio(url)
                audio_paths.append(audio_path)

                # 执行ASR转写
                asr_result = transcriber.transcribe(audio_path)

                all_results.append({
                    "index": i,
                    "url": url,
                    "text": asr_result.text,
                })
                completed += 1
                logger.info(f"Task {task_id} [{i+1}/{total}]: Transcribed {len(asr_result.text)} chars")

            except Exception as e:
                failed += 1
                logger.error(f"Task {task_id} [{i+1}/{total}] failed: {e}")
                all_results.append({
                    "index": i,
                    "url": url,
                    "error": str(e),
                })

        # 追加新的ASR文本
        new_texts = [r["text"] for r in all_results if "text" in r]
        all_texts = existing_texts + new_texts

        if not new_texts:
            logger.error(f"Task {task_id}: No successful new transcriptions")
            return

        # 重新计算人格画像
        extractor = PersonalityExtractor()
        profile = extractor.extract(
            texts=all_texts,
            author_name=existing_persona.name,
        )

        # 构建更新字典（与数据库字段对应）
        updates = {
            "name": profile.name,
            "verbal_tics": profile.verbal_tics,
            "grammar_prefs": profile.grammar_prefs,
            "logic_architecture": {
                "opening_style": profile.logic_architecture.opening_style,
                "transition_patterns": profile.logic_architecture.transition_patterns,
                "closing_style": profile.logic_architecture.closing_style,
                "topic_organization": profile.logic_architecture.topic_organization,
            },
            "temporal_patterns": {
                "avg_pause_duration": profile.temporal_patterns.avg_pause_duration,
                "pause_frequency": profile.temporal_patterns.pause_frequency,
                "speech_rhythm": profile.temporal_patterns.speech_rhythm,
                "excitement_curve": profile.temporal_patterns.excitement_curve,
            },
            "raw_json": {
                "status": "upgraded",
                "task_id": task_id,
                "previous_video_count": len(existing_texts),
                "new_video_count": total,
                "successful_new_count": completed,
                "failed_new_count": failed,
            },
            "source_asr_texts": all_texts,
        }

        await persona_repo.update(persona_id, updates)
        logger.info(f"Task {task_id}: Persona {persona_id} upgraded successfully with {len(all_texts)} total videos")

    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}")
    finally:
        # 清理临时文件
        for audio_path in audio_paths:
            try:
                downloader.cleanup(audio_path)
            except Exception:
                pass
        transcriber.release()


@router.get("/asr/tasks/{task_id}/status")
async def get_asr_task_status(task_id: str):
    """
    GET /v1/asr/tasks/{task_id}/status

    查询B站ASR任务状态
    """
    try:
        status = await task_repo.get_status(task_id)

        return {
            "task_id": task_id,
            "status": status.get("status", "unknown"),
            "history": status.get("history_versions", []),
            "best_text": status.get("best_text", ""),
        }

    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail={"error": "Task not found", "task_id": task_id})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "InternalError", "message": str(e)})


@router.get("/health")
async def health_check():
    """
    GET /v1/health

    健康检查
    """
    from persona_engine.storage.database import database

    db_healthy = await database.health_check()

    return {
        "status": "healthy" if db_healthy else "degraded",
        "database": "connected" if db_healthy else "disconnected",
        "timestamp": datetime.now().isoformat(),
    }

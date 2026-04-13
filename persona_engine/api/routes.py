"""
FastAPI 路由

提供本地 API 接口供 .exe 调用
"""

import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path
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
from persona_engine.asr.bilibili_downloader import (
    BilibiliSpaceDownloader,
    is_valid_bilibili_space_url,
    extract_uid_from_space_url,
    build_video_url_from_bv,
)


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
        # 检查参数：source_texts、video_urls、space_url 至少要有一个
        has_texts = request.source_texts and len(request.source_texts) > 0
        has_videos = request.video_urls and len(request.video_urls) > 0
        has_space = bool(request.space_url)

        if not has_texts and not has_videos and not has_space:
            raise ValidationError(
                message="At least one of source_texts, video_urls, or space_url is required",
                field="source_texts/video_urls/space_url",
            )

        # 如果提供了 space_url，先获取视频列表
        if has_space and not has_videos and not has_texts:
            # 验证空间链接格式
            if not is_valid_bilibili_space_url(request.space_url):
                raise ValidationError(
                    message="Invalid Bilibili space URL format",
                    field="space_url",
                )

            # 从空间链接提取UID
            uid = extract_uid_from_space_url(request.space_url)
            if not uid:
                raise ValidationError(
                    message="Failed to extract UID from space URL",
                    field="space_url",
                )

            # 获取UP主空间视频列表（带超时，避免长时间阻塞）
            # 注意：space_downloader 内部已有指数退避重试，这里 timeout 限制总等待时间
            logger.info(f"Fetching videos from space for UID: {uid}")
            space_downloader = BilibiliSpaceDownloader()
            try:
                # 使用 asyncio.wait_for 限制总超时（秒），超时会抛出 TimeoutError
                space_videos = await asyncio.wait_for(
                    space_downloader.get_uploader_videos(uid=uid, limit=30),
                    timeout=60.0,
                )
            except asyncio.TimeoutError:
                raise BilibiliDownloadError(
                    message=f"获取空间视频超时（60秒），B站接口响应过慢，请稍后重试或检查Cookie是否有效",
                    details={"uid": uid},
                )

            if not space_videos:
                raise ValidationError(
                    message="No videos found in this space",
                    field="space_url",
                )

            # 将BV号转换为完整URL
            video_urls = [build_video_url_from_bv(v.bv_id) for v in space_videos]
            logger.info(f"Got {len(video_urls)} video URLs from space {uid}")

            # 更新请求的video_urls，继续使用现有流程
            request.video_urls = video_urls
            has_videos = True

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


@router.delete("/tasks/{task_id}")
async def cancel_task(task_id: str):
    """
    DELETE /v1/tasks/{task_id}

    取消正在运行的任务
    task_id 可以是：
    - persona_xxx（后台任务ID格式）
    - xxx（直接传 persona_id）
    """
    try:
        # 标准化 task_id：如果不是 "persona_" 开头，说明传的是 persona_id
        normalized_task_id = task_id if task_id.startswith("persona_") else f"persona_{task_id}"

        # 从 task_registry 取消 asyncio 任务
        cancelled = task_registry.cancel(normalized_task_id)

        # 同时尝试用原始 task_id 取消（兼容没有 "persona_" 前缀的情况）
        if not cancelled and task_id != normalized_task_id:
            cancelled = task_registry.cancel(task_id)

        # 更新 personas 表的 raw_json.status 为 cancelled
        # 这会被 run_persona_from_videos_task 中的 _is_task_cancelled() 检查点读取
        persona_id = task_id if not task_id.startswith("persona_") else task_id[len("persona_"):]
        try:
            existing = await persona_repo.get_by_id(persona_id)
            if existing and existing.raw_json:
                import json as _json
                raw = existing.raw_json if isinstance(existing.raw_json, dict) else _json.loads(existing.raw_json)
                raw["status"] = "cancelled"
                await persona_repo.update(persona_id, {"raw_json": raw})
        except Exception:
            pass  # persona 可能不存在，不影响取消流程

        return {
            "task_id": task_id,
            "cancelled": True,
            "message": "任务已取消",
        }

    except PersonaEngineException as e:
        raise HTTPException(status_code=500, detail=e.to_dict())


@router.delete("/video-tasks/{task_id}")
async def cancel_video_task(task_id: str):
    """
    DELETE /v1/video-tasks/{task_id}

    取消视频处理任务（PRD 5.1 定义的标准接口）
    支持通过 persona_id 直接取消视频人格创建任务

    脏数据条件清理逻辑：
    - 如果尚未提取到任何 ASR 文本，物理删除该空壳 Persona
    - 如果已有部分 ASR 文本，保留数据并标记为 partial_completed
    """
    try:
        # 视频任务的 task_id 格式为 persona_xxx
        normalized_task_id = task_id if task_id.startswith("persona_") else f"persona_{task_id}"

        # 1. 尝试从 task_registry 取消 asyncio 协程
        cancelled = task_registry.cancel(normalized_task_id)

        # 2. 兼容：也尝试原始 task_id（不带 persona_ 前缀）
        if not cancelled and task_id != normalized_task_id:
            cancelled = task_registry.cancel(task_id)

        # 3. 获取 persona_id 并执行脏数据条件清理
        persona_id = task_id if not task_id.startswith("persona_") else task_id[len("persona_"):]
        response_message = "取消指令已下发，后台算力资源将在数秒内释放。"

        try:
            existing = await persona_repo.get_by_id(persona_id)
            if existing:
                # 检查已提取的 ASR 文本数量
                asr_texts = existing.source_asr_texts or []

                if len(asr_texts) == 0:
                    # 尚未提取到任何语料：这是一个空壳数据，执行物理删除
                    await persona_repo.delete(persona_id)
                    response_message += " 由于未提取到任何语料，已物理删除该空壳人格数据。"
                    logger.info(f"Task {task_id}: No ASR texts extracted, physically deleted persona {persona_id}")
                else:
                    # 已经有部分语料：保留数据，更新状态为 partial_completed
                    import json as _json
                    raw = existing.raw_json if isinstance(existing.raw_json, dict) else _json.loads(existing.raw_json)
                    raw["status"] = "partial_completed"
                    await persona_repo.update(persona_id, {
                        "raw_json": raw,
                        "source_asr_texts": asr_texts,
                    })
                    response_message += f" 已成功保留 {len(asr_texts)} 个视频的语料，人格状态更新为[部分完成]。"
                    logger.info(f"Task {task_id}: Partial ASR texts ({len(asr_texts)}), marked as partial_completed")
            else:
                logger.warning(f"Task {task_id}: Persona not found")

        except PersonaNotFoundError:
            logger.warning(f"Task {task_id}: Persona {persona_id} not found, nothing to clean")
        except Exception as e:
            logger.error(f"Task {task_id}: Failed to process persona cleanup: {e}")

        return {
            "task_id": task_id,
            "status": "cancelled",
            "message": response_message,
        }

    except PersonaEngineException as e:
        raise HTTPException(status_code=500, detail=e.to_dict())


@router.get("/tasks/interrupted")
async def get_interrupted_tasks():
    """
    GET /v1/tasks/interrupted

    获取所有被中断的任务（服务器重启前正在运行的任务）
    """
    try:
        tasks = await task_repo.get_interrupted_tasks()
        return {
            "count": len(tasks),
            "tasks": tasks,
        }
    except PersonaEngineException as e:
        raise HTTPException(status_code=500, detail=e.to_dict())


@router.post("/asr/from-url", response_model=BilibiliASRResponse)
async def bilibili_asr(request: BilibiliASRRequest):
    """
    POST /v1/asr/from-url

    输入B站视频链接，自动下载并提取ASR文本
    支持单条或多条链接（多行）

    ==========================================================================
    B站下载入口 #1 - ASR文本提取
    ==========================================================================
    调用链: bilibili_asr() -> run_bilibili_asr_task() -> BilibiliDownloader
    反爬风险: 中等（单视频请求，触发概率较低）

    后续统一优化请联系：
    - BilibiliDownloader 类 (bilibili_downloader.py)
    - get_uploader_videos() 如需空间列表获取优化
    ==========================================================================
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

    ==========================================================================
    B站下载入口 #2 - ASR后台任务（被 bilibili_asr 调用）
    ==========================================================================
    调用链: run_bilibili_asr_task() -> BilibiliDownloader.download_and_extract_audio()
    反爬风险: 中等（批量请求，建议添加请求间隔）

    进度追踪: 通过 task_repo.update_result() 更新 history_versions
    统一优化请联系: BilibiliDownloader 类 (bilibili_downloader.py)
    ==========================================================================
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

                # 立即保存中间结果（断点续传）
                await task_repo.update_result(
                    task_id=task_id,
                    best_text="",
                    best_score=0.0,
                    best_iteration=0,
                    history_versions=[{
                        "status": f"processing ({i+1}/{total})",
                        "url": url,
                        "phase": "completed",
                        "progress": ((i + 1) / total) * 100,
                    }],
                    status="running",
                    intermediate_results=all_results.copy(),
                )

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


async def _update_persona_progress(
    persona_id: str,
    completed: int,
    total: int,
    current_index: int | None = None,
    current_phase: str = "downloading",
    current_progress: float = 0.0,
    current_bv_id: str = None,
    failed: int = 0,
):
    """
    更新人格进度到数据库

    Args:
        persona_id: 人格ID
        completed: 已完成视频数
        total: 视频总数
        current_index: 当前处理的视频索引（从0开始）
        current_phase: 当前阶段 (downloading/transcribing)
        current_progress: 当前视频的进度百分比
        current_bv_id: 当前处理的视频BV号
        failed: 失败的视频数
    """
    try:
        raw_json = {
            "status": "processing",
            "task_id": f"persona_{persona_id}",
            "progress": f"{completed}/{total}",
            "completed_videos": completed,
            "total_videos": total,
            "failed_videos": failed,
        }

        # 添加当前视频详细信息
        if current_index is not None:
            raw_json["current_video"] = {
                "index": current_index,
                "phase": current_phase,
                "progress": current_progress,
                "bv_id": current_bv_id,
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
    后台任务：从视频创建新人格（带检查点机制和子进程强杀）

    ==========================================================================
    B站下载入口 #3 - 创建人格后台任务
    ==========================================================================
    调用链: create_persona() -> run_persona_from_videos_task() -> BilibiliDownloader
    支持入口: video_urls (直接链接) 和 space_url (通过 BilibiliSpaceDownloader 转换)
    反爬风险: 高（30个视频批量处理，极易触发412）

    进度追踪: 通过 _update_persona_progress() 实时更新到 personas.raw_json
    统一优化请联系: BilibiliDownloader 类 (bilibili_downloader.py)
    ==========================================================================
    """
    import re as regex_module
    import os
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

    def extract_bv_from_url(url: str) -> str:
        """从URL提取BV号"""
        match = regex_module.search(r'BV[\w]+', url)
        return match.group(0) if match else url

    def create_progress_callback(persona_id: str, total: int, i: int, bv_id: str):
        """创建进度回调函数"""
        last_update_time = [0]  # 用于限制更新频率

        def progress_callback(progress: float, status: str):
            # 每2秒更新一次进度，避免过于频繁的数据库写入
            current_time = asyncio.get_event_loop().time()
            if current_time - last_update_time[0] < 2.0:
                return
            last_update_time[0] = current_time

            asyncio.create_task(_update_persona_progress(
                persona_id=persona_id,
                completed=completed,
                total=total,
                current_index=i,
                current_phase="downloading",
                current_progress=progress,
                current_bv_id=bv_id,
                failed=failed,
            ))
        return progress_callback

    async def _is_task_cancelled(persona_id: str) -> bool:
        """检查任务是否已被取消"""
        try:
            persona = await persona_repo.get_by_id(persona_id)
            if persona and persona.raw_json:
                import json as _json
                raw = persona.raw_json if isinstance(persona.raw_json, dict) else _json.loads(persona.raw_json)
                return raw.get("status") == "cancelled"
        except Exception:
            pass
        return False

    async def extract_asr_with_checkpoint(persona_id: str, audio_path: str) -> str | None:
        """执行 Whisper 转写，通过并行协程监控取消状态并强制释放算力"""
        from persona_engine.core.config import config as engine_config

        whisper_config = engine_config.whisper
        cmd = [
            "whisper", audio_path,
            "--model", whisper_config.model_size,
            "--language", whisper_config.language or "zh",
            "--device", whisper_config.device or "cpu",
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as e:
            logger.error(f"启动 Whisper 进程失败: {e}")
            # 降级到同步转写
            asr_result = transcriber.transcribe(audio_path)
            return asr_result.text if asr_result else ""

        cancel_flag = False

        async def watch_cancel():
            nonlocal cancel_flag
            while process.returncode is None:
                await asyncio.sleep(2)  # 每 2 秒检查一次状态
                if await _is_task_cancelled(persona_id):
                    logger.info(f"[Task persona_{persona_id}] 任务被取消！强杀 Whisper (PID: {process.pid})")
                    cancel_flag = True
                    try:
                        process.terminate()
                    except Exception:
                        pass
                    break

        # 启动监控任务
        watcher = asyncio.create_task(watch_cancel())

        # 等待进程执行完毕（或被 kill）
        try:
            stdout, stderr = await process.communicate()
        except Exception as e:
            logger.error(f"Whisper 进程通信错误: {e}")
            watcher.cancel()
            return None

        watcher.cancel()

        if cancel_flag:
            return None

        if process.returncode != 0:
            logger.error(f"Whisper 进程异常退出 (code={process.returncode}): {stderr.decode()}")
            return None

        return stdout.decode('utf-8').strip()

    try:
        total = len(video_urls)
        logger.info(f"Task {task_id}: Starting persona creation from {total} videos")

        # 基础超时配置（兜底）
        BASE_DL_TIMEOUT = 180  # 3分钟
        BASE_ASR_TIMEOUT = 60  # 1分钟

        for i, url in enumerate(video_urls):
            bv_id = extract_bv_from_url(url)

            # 【检查点 1】：下载前状态检查
            if await _is_task_cancelled(persona_id):
                logger.info(f"[Task {task_id}] 检测到取消信号，停止下载 {url}")
                break

            # ==========================================
            # 步骤 0：获取视频时长，用于动态计算超时
            # ==========================================
            try:
                video_info = await downloader.get_video_info(url)
                duration_sec = video_info.get("duration", 0)
                if duration_sec <= 0:
                    duration_sec = 600  # 默认 10 分钟
                logger.info(f"[Task {task_id}] 视频 {bv_id} 时长: {duration_sec} 秒")
            except Exception as e:
                logger.warning(f"[Task {task_id}] 获取视频 {bv_id} 信息失败: {e}，使用默认时长 600 秒")
                duration_sec = 600

            # 动态超时计算
            # 下载超时：基础 3 分钟 + 视频时长 * 0.2（网络情况不好时留足余量）
            dl_timeout = BASE_DL_TIMEOUT + (duration_sec * 0.2)
            # 转写超时：基础 1 分钟 + 视频时长 * 2.5（保护本地显卡/CPU不被无限占用）
            asr_timeout = BASE_ASR_TIMEOUT + (duration_sec * 2.5)

            try:
                logger.info(f"Task {task_id} [{i+1}/{total}]: Downloading {url} (动态超时: {dl_timeout:.0f}秒)")

                # 更新进度为开始下载
                await _update_persona_progress(
                    persona_id=persona_id,
                    completed=completed,
                    total=total,
                    current_index=i,
                    current_phase="downloading",
                    current_progress=0.0,
                    current_bv_id=bv_id,
                    failed=failed,
                )

                # 创建进度回调
                progress_cb = create_progress_callback(persona_id, total, i, bv_id)

                # 【步骤 1】：动态超时下载
                audio_path = await asyncio.wait_for(
                    downloader.download_and_extract_audio(url, progress_callback=progress_cb),
                    timeout=dl_timeout,
                )
                audio_paths.append(audio_path)

                # 【检查点 2】：转写前状态检查与垃圾清理
                if await _is_task_cancelled(persona_id):
                    logger.info(f"[Task {task_id}] 检测到取消信号，放弃转写并清理: {audio_path}")
                    if os.path.exists(audio_path):
                        os.remove(audio_path)
                    break

                # 更新进度为转写阶段
                await _update_persona_progress(
                    persona_id=persona_id,
                    completed=completed,
                    total=total,
                    current_index=i,
                    current_phase="transcribing",
                    current_progress=50.0,
                    current_bv_id=bv_id,
                    failed=failed,
                )

                # 【步骤 2】：动态超时转写（Whisper）
                logger.info(f"Task {task_id} [{i+1}/{total}]: 开始转写 (动态超时: {asr_timeout:.0f}秒)")
                asr_text = await asyncio.wait_for(
                    extract_asr_with_checkpoint(persona_id, audio_path),
                    timeout=asr_timeout,
                )

                # 返回 None 说明转写被中途中断（用户取消）
                if asr_text is None:
                    logger.info(f"[Task {task_id}] 转写被强制中断，清理文件: {audio_path}")
                    if os.path.exists(audio_path):
                        os.remove(audio_path)
                    break

                # 检查是否为空文本
                if not asr_text or len(asr_text.strip()) == 0:
                    logger.warning(f"[Task {task_id}] 转写结果为空，跳过: {url}")
                    failed += 1
                    if os.path.exists(audio_path):
                        os.remove(audio_path)
                    await _update_persona_progress(
                        persona_id=persona_id,
                        completed=completed,
                        total=total,
                        current_index=i,
                        current_phase="failed",
                        current_progress=0.0,
                        current_bv_id=bv_id,
                        failed=failed,
                    )
                    continue

                all_results.append({
                    "index": i,
                    "url": url,
                    "bv_id": bv_id,
                    "text": asr_text,
                })
                completed += 1
                logger.info(f"Task {task_id} [{i+1}/{total}]: Transcribed {len(asr_text)} chars")

                # 每完成1个视频即更新进度
                await _update_persona_progress(
                    persona_id=persona_id,
                    completed=completed,
                    total=total,
                    current_index=i,
                    current_phase="completed",
                    current_progress=100.0,
                    current_bv_id=bv_id,
                    failed=failed,
                )

                # 正常完成清理临时音频
                if os.path.exists(audio_path):
                    os.remove(audio_path)

            except asyncio.TimeoutError:
                failed += 1
                timeout_type = "下载" if not audio_paths or url not in str(audio_paths) else "转写"
                logger.error(f"[Task {task_id}] [{i+1}/{total}] {timeout_type}超时 ({dl_timeout:.0f}s 或 {asr_timeout:.0f}s)！跳过视频: {url}")
                all_results.append({
                    "index": i,
                    "url": url,
                    "bv_id": bv_id,
                    "error": f"Timeout ({timeout_type}) after {dl_timeout:.0f}s/{asr_timeout:.0f}s",
                })
                # 确保临时文件被清理
                if 'audio_path' in locals() and os.path.exists(audio_path):
                    os.remove(audio_path)
                # 更新失败进度
                await _update_persona_progress(
                    persona_id=persona_id,
                    completed=completed,
                    total=total,
                    current_index=i,
                    current_phase="failed",
                    current_progress=0.0,
                    current_bv_id=bv_id,
                    failed=failed,
                )
            except Exception as e:
                failed += 1
                logger.error(f"Task {task_id} [{i+1}/{total}] failed: {e}")
                all_results.append({
                    "index": i,
                    "url": url,
                    "bv_id": bv_id,
                    "error": str(e),
                })
                # 确保临时文件被清理
                if 'audio_path' in locals() and os.path.exists(audio_path):
                    os.remove(audio_path)
                # 更新失败进度
                await _update_persona_progress(
                    persona_id=persona_id,
                    completed=completed,
                    total=total,
                    current_index=i,
                    current_phase="failed",
                    current_progress=0.0,
                    current_bv_id=bv_id,
                    failed=failed,
                )

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

    ==========================================================================
    B站下载入口 #4 - 追加视频后台任务
    ==========================================================================
    调用链: add_videos_to_persona() -> run_persona_upgrade_task() -> BilibiliDownloader
    反爬风险: 中等（批量请求，取决于追加视频数量）

    注意: 此函数目前缺少详细进度追踪（TODO: 统一进度追踪机制）
    统一优化请联系: BilibiliDownloader 类 (bilibili_downloader.py)
    ==========================================================================
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


# ========== B站配置路由 ==========

class BilibiliConfigResponse(BaseModel):
    """B站配置响应"""
    cookie: str = ""
    access_token: str = ""
    min_interval: float = 3.0
    max_interval: float = 10.0
    delay_per_page: float = 5.0
    max_retries: int = 5
    retry_base_delay: float = 2.0
    user_agent: str = ""
    api_mode: str = "web"


class BilibiliConfigUpdateRequest(BaseModel):
    """B站配置更新请求"""
    cookie: str | None = None
    access_token: str | None = None
    min_interval: float | None = None
    max_interval: float | None = None
    delay_per_page: float | None = None
    max_retries: int | None = None
    retry_base_delay: float | None = None
    user_agent: str | None = None
    api_mode: str | None = None


@router.get("/config/bilibili", response_model=BilibiliConfigResponse)
async def get_bilibili_config():
    """
    GET /v1/config/bilibili

    获取B站下载配置（不包含敏感信息明文）
    参考BBDown: https://github.com/nilaoda/BBDown
    """
    try:
        from persona_engine.core.config import config
        bili = config.bilibili

        # 返回完整cookie（前端使用 type="password"，不会明文显示）
        return BilibiliConfigResponse(
            cookie=bili.cookie,
            access_token=bili.access_token if bili.access_token else "",
            min_interval=bili.min_interval,
            max_interval=bili.max_interval,
            delay_per_page=bili.delay_per_page,
            max_retries=bili.max_retries,
            retry_base_delay=bili.retry_base_delay,
            user_agent=bili.user_agent[:50] + "..." if len(bili.user_agent) > 50 else bili.user_agent,
            api_mode=bili.api_mode,
        )
    except Exception as e:
        logger.error(f"Failed to get bilibili config: {e}")
        raise HTTPException(status_code=500, detail={"error": "InternalError", "message": str(e)})


@router.put("/config/bilibili")
async def update_bilibili_config(request: BilibiliConfigUpdateRequest):
    """
    PUT /v1/config/bilibili

    更新B站下载配置（会写入 config.yaml）
    参考BBDown: https://github.com/nilaoda/BBDown

    支持的更新字段：
    - cookie: B站登录Cookie (SESSDATA等)
    - access_token: TV/App接口Token
    - min_interval/max_interval: 请求间隔范围(秒)
    - delay_per_page: 页面间延迟(秒)
    - max_retries: 最大重试次数
    - retry_base_delay: 指数退避基数(秒)
    - user_agent: User-Agent字符串
    - api_mode: API模式 (web/tv/app/intl)
    """
    try:
        from persona_engine.core.config import config

        # 获取当前配置
        bili = config.bilibili
        current_config = {
            "cookie": bili.cookie,
            "access_token": bili.access_token,
            "min_interval": bili.min_interval,
            "max_interval": bili.max_interval,
            "delay_per_page": bili.delay_per_page,
            "max_retries": bili.max_retries,
            "retry_base_delay": bili.retry_base_delay,
            "user_agent": bili.user_agent,
            "api_mode": bili.api_mode,
        }

        # 合并更新（只更新非None的字段）
        updates = request.model_dump(exclude_unset=True)
        current_config.update(updates)

        # 写入配置文件
        config_path = Path(__file__).parent.parent.parent / "config.yaml"
        if config_path.exists():
            import yaml
            with open(config_path, "r", encoding="utf-8") as f:
                yaml_config = yaml.safe_load(f) or {}
        else:
            yaml_config = {}

        # 更新bilibili配置
        yaml_config["bilibili"] = current_config

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(yaml_config, f, allow_unicode=True, default_flow_style=False)

        # 重新加载配置
        config.reload()

        return {
            "message": "配置已更新",
            "config": BilibiliConfigResponse(
                cookie=current_config["cookie"],
                access_token=current_config["access_token"],
                min_interval=current_config["min_interval"],
                max_interval=current_config["max_interval"],
                delay_per_page=current_config["delay_per_page"],
                max_retries=current_config["max_retries"],
                retry_base_delay=current_config["retry_base_delay"],
                user_agent=current_config["user_agent"],
                api_mode=current_config["api_mode"],
            ),
        }
    except Exception as e:
        logger.error(f"Failed to update bilibili config: {e}")
        raise HTTPException(status_code=500, detail={"error": "InternalError", "message": str(e)})


@router.get("/bilibili/space/preview")
async def preview_bilibili_space(space_url: str):
    """
    GET /v1/bilibili/space/preview?space_url=xxx

    预览B站UP主空间视频列表，不创建人格。
    用于测试Cookie是否有效、空间链接是否可访问。
    返回前10个视频的标题和BV号。
    """
    try:
        # 验证URL格式
        if not is_valid_bilibili_space_url(space_url):
            raise HTTPException(status_code=400, detail={"error": "ValidationError", "message": "Invalid Bilibili space URL format"})

        # 提取UID
        uid = extract_uid_from_space_url(space_url)
        if not uid:
            raise HTTPException(status_code=400, detail={"error": "ValidationError", "message": "Failed to extract UID from space URL"})

        # 尝试获取视频列表（不带重试，只试一次，快速反馈）
        space_downloader = BilibiliSpaceDownloader()
        try:
            videos = await asyncio.wait_for(
                space_downloader.get_uploader_videos(uid=uid, limit=10),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            raise BilibiliDownloadError(
                message="获取空间视频超时（30秒），B站接口响应过慢，可能Cookie已过期或IP被限制",
                details={"uid": uid},
            )

        if not videos:
            raise HTTPException(status_code=400, detail={"error": "ValidationError", "message": "该空间没有找到视频或Cookie无权访问"})

        return {
            "uid": uid,
            "total_found": len(videos),
            "videos": [{"bv_id": v.bv_id, "title": v.title, "duration": v.duration} for v in videos],
        }
    except BilibiliDownloadError as e:
        raise HTTPException(status_code=500, detail=e.to_dict())
    except HTTPException:
        raise  # 让 FastAPI 默认处理
    except Exception as e:
        logger.error(f"Space preview failed: {e}")
        raise HTTPException(status_code=500, detail={"error": "InternalError", "message": str(e)})

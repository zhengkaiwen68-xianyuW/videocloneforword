"""
人格管理路由

POST   /personas             创建人格
GET    /personas             获取所有
GET    /personas/{id}        获取详情
PUT    /personas/{id}        更新
DELETE /personas/{id}        删除
POST   /personas/{id}/videos 追加视频
"""

import asyncio
import logging
import uuid

from fastapi import APIRouter, HTTPException

from persona_engine.core.exceptions import (
    PersonaNotFoundError,
    ValidationError,
    PersonaEngineException,
    BilibiliDownloadError,
)
from persona_engine.core.types import (
    PersonaCreateRequest,
    PersonaUpdateRequest,
    PersonaAddVideosRequest,
    PersonalityProfile,
    LogicArchitecture,
    TemporalPattern,
    DeepPsychology,
)
from persona_engine.core.task_registry import task_registry
from persona_engine.api.dependencies import persona_repo, video_task_repo, concurrency
from persona_engine.api.models import (
    PersonaResponse,
    PersonaListResponse,
    PersonaCreateResponse,
)
from persona_engine.asr.personality_extractor import PersonalityExtractor
from persona_engine.asr.bilibili_downloader import (
    BilibiliSpaceDownloader,
    is_valid_bilibili_space_url,
    extract_uid_from_space_url,
    build_video_url_from_bv,
)
from persona_engine.api.background_tasks import (
    _run_persona_from_videos_task_with_tracking,
    _run_persona_upgrade_task_with_tracking,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ── 辅助函数：构建 PersonaResponse ──

def _persona_to_response(persona) -> PersonaResponse:
    """将 PersonalityProfile 转换为 PersonaResponse（消除重复代码）"""
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
        deep_psychology={
            "emotional_tone": persona.deep_psychology.emotional_tone,
            "emotional_arc": persona.deep_psychology.emotional_arc,
            "rhetorical_devices": persona.deep_psychology.rhetorical_devices,
            "lexicon": persona.deep_psychology.lexicon,
        },
        raw_json=persona.raw_json,
        created_at=persona.created_at.isoformat(),
        updated_at=persona.updated_at.isoformat(),
    )


# ── 路由 ──

@router.get("/personas", response_model=PersonaListResponse)
async def get_personas():
    """
    GET /v1/personas

    获取已存储的人格清单
    """
    try:
        personas = await persona_repo.get_all()
        return PersonaListResponse(
            personas=[_persona_to_response(p) for p in personas],
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
            logger.info(f"Fetching videos from space for UID: {uid}")
            space_downloader = BilibiliSpaceDownloader()
            try:
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

            # 创建视频处理任务记录（用于断点续传）
            await video_task_repo.create(
                task_id=task_id,
                persona_id=persona_id,
                video_urls=request.video_urls,
            )

            # 启动后台任务：从视频提取ASR并计算人格
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
            task.add_done_callback(lambda t, tid=task_id: task_registry.unregister(tid))
            logger.info(f"Task {task_id} fully registered, done={task.done()}")

            return PersonaCreateResponse(
                id=persona_id,
                name=request.name,
                message="Persona created, processing videos in background",
            )

        # 如果提供了 ASR 文本，直接生成人格
        extractor = PersonalityExtractor()
        profile = await extractor.extract(
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
        return _persona_to_response(persona)

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
        return _persona_to_response(persona)

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

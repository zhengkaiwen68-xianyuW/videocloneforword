"""
ASR/视频处理路由

POST /asr/from-url           B站视频 ASR 提取
GET  /asr/tasks/{id}/status  ASR 任务状态查询
"""

import asyncio
import logging
import uuid

from fastapi import APIRouter, HTTPException

from persona_engine.core.exceptions import TaskNotFoundError
from persona_engine.core.task_registry import task_registry
from persona_engine.api.dependencies import task_repo, concurrency
from persona_engine.api.models import BilibiliASRRequest, BilibiliASRResponse
from persona_engine.api.background_tasks import run_bilibili_asr_task

logger = logging.getLogger(__name__)
router = APIRouter()


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

        # 检查并发任务数限制
        if not await concurrency.acquire_task(task_id):
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "TooManyTasks",
                    "message": f"并发任务已满（最大 {concurrency.get_status()['tasks']['max']} 个），请等待当前任务完成后再试",
                    "code": "TASK_LIMIT_EXCEEDED",
                },
            )

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

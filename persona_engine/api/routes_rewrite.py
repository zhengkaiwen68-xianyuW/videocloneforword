"""
重写任务路由

POST /process/batch   发起批量洗稿
"""

import asyncio
import logging
import uuid

from fastapi import APIRouter, HTTPException

from persona_engine.core.exceptions import PersonaEngineException
from persona_engine.core.task_registry import task_registry
from persona_engine.api.dependencies import task_repo
from persona_engine.api.models import BatchRewriteRequestModel
from persona_engine.api.background_tasks import run_rewrite_task

logger = logging.getLogger(__name__)
router = APIRouter()


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
            task.add_done_callback(lambda t, tid=task_id: task_registry.unregister(tid))

            task_ids.append(task_id)

        return {
            "batch_id": batch_id,
            "task_ids": task_ids,
            "total_count": len(task_ids),
        }

    except PersonaEngineException as e:
        raise HTTPException(status_code=500, detail=e.to_dict())

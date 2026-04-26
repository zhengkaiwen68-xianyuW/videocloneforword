"""
任务管理路由

GET    /tasks                    列出所有后台任务
GET    /tasks/{id}/status        查询重写迭代进度
GET    /tasks/{id}/result        获取最终结果
DELETE /tasks/{id}               取消任务
GET    /tasks/interrupted        中断任务列表
GET    /tasks/recent             最近完成
GET    /video-tasks              视频处理任务列表
DELETE /video-tasks/{id}         取消视频任务
"""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException

from persona_engine.core.exceptions import (
    PersonaNotFoundError,
    TaskNotFoundError,
    PersonaEngineException,
)
from persona_engine.core.task_registry import task_registry
from persona_engine.api.dependencies import persona_repo, task_repo, video_task_repo
from persona_engine.api.models import TaskStatusResponse, TaskResultResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/tasks/{task_id}/status", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """
    GET /v1/tasks/{id}/status

    查询重写迭代进度与当前最高分
    """
    try:
        status = await task_repo.get_status(task_id)

        # 计算已用时间
        created_at_str = status.get("created_at")
        elapsed_seconds = 0.0
        if created_at_str:
            try:
                created_at = datetime.fromisoformat(created_at_str)
                elapsed_seconds = (datetime.now() - created_at).total_seconds()
            except Exception:
                elapsed_seconds = 0.0

        return TaskStatusResponse(
            task_id=status["task_id"],
            status=status["status"],
            iteration=status.get("best_iteration", 0),
            current_score=status["best_score"],
            best_score=status["best_score"],
            best_text=status["best_text"],
            history_count=status["history_count"],
            elapsed_seconds=round(elapsed_seconds, 1),
        )

    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail={"error": "Task not found", "task_id": task_id})
    except PersonaEngineException as e:
        raise HTTPException(status_code=500, detail=e.to_dict())


@router.get("/tasks/{task_id}/result", response_model=TaskResultResponse)
async def get_task_result(task_id: str):
    """
    GET /v1/tasks/{id}/result

    获取重写任务的最终结果（用于历史记录恢复）
    """
    try:
        status = await task_repo.get_status(task_id)

        # 只有已完成的任务才返回结果
        if status["status"] not in ("completed", "completed_below_threshold"):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "TaskNotCompleted",
                    "message": f"Task is not completed, current status: {status['status']}",
                    "task_id": task_id,
                },
            )

        return TaskResultResponse(
            task_id=status["task_id"],
            status=status["status"],
            best_text=status["best_text"],
            best_score=status["best_score"],
            best_iteration=status.get("best_iteration", 0),
            completed_at=status.get("completed_at"),
        )

    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail={"error": "Task not found", "task_id": task_id})
    except HTTPException:
        raise
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
        persona_id = task_id if not task_id.startswith("persona_") else task_id[len("persona_"):]
        try:
            existing = await persona_repo.get_by_id(persona_id)
            if existing and existing.raw_json:
                raw = existing.raw_json if isinstance(existing.raw_json, dict) else json.loads(existing.raw_json)
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

        # 3.1 更新 VideoTask 状态为 cancelled
        try:
            await video_task_repo.update_status(normalized_task_id, "cancelled")
        except Exception as e:
            logger.warning(f"Task {task_id}: Failed to update video task status: {e}")

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
                    raw = existing.raw_json if isinstance(existing.raw_json, dict) else json.loads(existing.raw_json)
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


@router.get("/video-tasks")
async def get_video_tasks():
    """
    GET /v1/video-tasks

    获取所有视频处理任务状态（使用 VideoTaskRepository 实现）
    返回所有任务及其实时状态
    """
    try:
        # 获取注册的所有任务ID（用于判断是否正在运行）
        registered_task_ids = task_registry.list_tasks()

        # 获取所有视频处理任务
        all_tasks = await video_task_repo.list_tasks(limit=100, offset=0)

        # 获取人格名称映射（使用批量查询避免 N+1 问题）
        persona_names = {}
        persona_ids = list(set(t.persona_id for t in all_tasks))
        if persona_ids:
            try:
                personas = await persona_repo.get_by_ids(persona_ids)
                for persona in personas:
                    persona_names[persona.id] = persona.name
            except Exception:
                pass  # 批量查询失败时保持为空，使用默认值

        # 构建任务列表
        tasks = []
        for task in all_tasks:
            # 判断是否为当前正在运行的任务
            is_registered = task.id in registered_task_ids

            # 计算进度
            total = len(task.video_urls) if task.video_urls else 0
            completed = len(task.completed_urls) if task.completed_urls else 0
            failed = len(task.failed_urls) if task.failed_urls else 0
            progress_percent = (completed / total * 100) if total > 0 else 0

            tasks.append({
                "task_id": task.id,
                "persona_id": task.persona_id,
                "name": persona_names.get(task.persona_id, "未知"),
                "status": task.status,
                "total_videos": total,
                "completed_videos": completed,
                "failed_videos": failed,
                "progress_percent": round(progress_percent, 1),
                "is_registered": is_registered,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            })

        return {
            "total": len(tasks),
            "tasks": tasks,
            "registered_tasks": registered_task_ids,
        }
    except PersonaEngineException as e:
        raise HTTPException(status_code=500, detail=e.to_dict())


@router.get("/tasks")
async def list_tasks():
    """
    GET /v1/tasks

    获取所有注册的后台任务（调试用）
    """
    return {
        "tasks": task_registry.list_tasks(),
    }


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


@router.get("/tasks/recent")
async def get_recent_completed_tasks():
    """
    GET /v1/tasks/recent

    获取最近完成的重写任务（用于前端恢复历史结果）
    """
    try:
        tasks = await task_repo.get_recent_completed_tasks(limit=10)
        return {
            "count": len(tasks),
            "tasks": tasks,
        }
    except PersonaEngineException as e:
        raise HTTPException(status_code=500, detail=e.to_dict())

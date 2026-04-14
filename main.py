"""
Persona Engine 启动入口

用于 PyInstaller 打包的入口点
"""
import sys
import os

# 获取应用目录
if getattr(sys, 'frozen', False):
    # PyInstaller 打包环境
    app_dir = sys._MEIPASS
    base_dir = os.path.dirname(sys.executable)
else:
    # 普通运行环境 - main.py在项目根目录下，所以只需要dirname一次
    app_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = app_dir

sys.path.insert(0, base_dir)
os.chdir(base_dir)

# =============================================================================
# 重要修复：yt-dlp 内部使用 asyncio.get_running_loop()，但在 run_in_executor
# 的工作线程中会失败。使用统一的 asyncio_patch 模块避免多处 patch 冲突。
# =============================================================================
from persona_engine.core.asyncio_patch import apply_patch
apply_patch()

# 设置环境变量让 SQLAlchemy 能找到模块
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# 延迟导入以确保路径正确
def get_app():
    import asyncio
    from persona_engine.core.config import config
    from persona_engine.core.exceptions import PersonaEngineException
    from persona_engine.storage.database import database
    from persona_engine.api.routes import router
    from persona_engine.core.task_registry import task_registry

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Starting Persona Engine API Server...")
        try:
            await database.create_tables()
            logger.info("Database tables initialized")

            # 清理卡死的任务（服务器异常关闭遗留）
            from persona_engine.storage.persona_repo import PersonaRepository
            from datetime import timedelta

            repo = PersonaRepository()
            stale_threshold = timedelta(hours=24)  # 超过24小时视为卡死（视频处理可能需要很长时间）
            stale_count = await repo.mark_stale_processing_as_failed(stale_threshold)
            if stale_count > 0:
                logger.warning(f"Cleaned up {stale_count} stale processing tasks from previous session")

            # 标记中断的任务（服务器正常关闭时任务应已正确结束）
            from persona_engine.storage.persona_repo import TaskRepository
            task_repo = TaskRepository()
            interrupted_count = await task_repo.mark_running_as_interrupted()
            if interrupted_count > 0:
                logger.warning(f"Marked {interrupted_count} interrupted tasks")

            # ==========================================================================
            # 断点续传扫描：检查并恢复未完成的视频处理任务
            # ==========================================================================
            from persona_engine.storage.persona_repo import VideoTaskRepository
            from persona_engine.api.routes import video_task_repo

            video_task_repo_instance = VideoTaskRepository()
            unfinished_tasks = await video_task_repo_instance.get_unfinished_tasks()

            if unfinished_tasks:
                logger.info(f"Found {len(unfinished_tasks)} unfinished video processing tasks, checking for resume...")

                for task in unfinished_tasks:
                    # 计算未完成的视频列表
                    completed_urls = set(task.completed_urls or [])
                    failed_urls = set(task.failed_urls or [])
                    all_urls = task.video_urls or []
                    total_count = len(all_urls)
                    completed_count = len(completed_urls)
                    failed_count = len(failed_urls)
                    remaining_urls = [
                        url for url in all_urls
                        if url not in completed_urls and url not in failed_urls
                    ]
                    remaining_count = len(remaining_urls)

                    # 检查关联的人格是否还存在
                    from persona_engine.storage.persona_repo import PersonaRepository
                    persona_repo = PersonaRepository()
                    persona = await persona_repo.get_by_id(task.persona_id)
                    persona_exists = persona is not None

                    if not remaining_urls:
                        # 所有视频都已处理完毕
                        if failed_count > 0:
                            # 有失败的视频：应该是 failed 状态，不是 completed
                            # 这是 Bug #013 的修复：不能因为 remaining_urls 为空就标记为 completed
                            logger.warning(
                                f"[Task {task.id}] All videos processed but {failed_count}/{total_count} failed. "
                                f"Marking as failed (not completed). "
                                f"completed={completed_count}, failed={failed_count}"
                            )
                            await video_task_repo_instance.update_status(task.id, "failed")
                        else:
                            # 全部成功
                            await video_task_repo_instance.update_status(task.id, "completed")
                            logger.info(
                                f"[Task {task.id}] All videos processed successfully, marked as completed "
                                f"({completed_count}/{total_count})"
                            )
                    elif not persona_exists:
                        # 有未完成视频但人格已被删除：无法继续
                        logger.warning(
                            f"[Task {task.id}] Cannot resume: persona '{task.persona_id}' not found. "
                            f"{remaining_count} videos remaining, {completed_count} completed, {failed_count} failed. "
                            f"Marking as failed."
                        )
                        await video_task_repo_instance.update_status(task.id, "failed")
                    else:
                        # 有未完成的视频且人格存在，需要继续处理
                        logger.info(
                            f"[Task {task.id}] Resuming with {remaining_count} remaining videos "
                            f"(persona='{persona.name}', {completed_count} completed, {failed_count} failed)"
                        )
                        # 注意：这里只更新状态为 pending，不自动启动恢复
                        # 真正的恢复应该在人格详情页面由用户触发
                        await video_task_repo_instance.update_status(task.id, "pending")
                        logger.info(f"[Task {task.id}] Marked as pending for manual resume")

        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")

        yield

        logger.info("Shutting down Persona Engine API Server...")

        # 取消所有后台任务并等待完成
        task_registry.cancel_all()
        logger.info("Waiting for background tasks to respond to cancellation...")
        try:
            await asyncio.wait_for(task_registry.wait_all(timeout=5.0), timeout=6.0)
            logger.info("All background tasks cancelled successfully")
        except asyncio.TimeoutError:
            logger.warning("Some background tasks did not respond to cancellation in time, forcing shutdown")

        # 关闭数据库连接
        await database.close()
        logger.info("Shutdown complete")

    app = FastAPI(
        title="Persona Engine API",
        description="短视频人格深度重构与洗稿引擎 - 本地 API 接口",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS 配置
    # 开发环境允许 localhost，生产环境应明确配置
    cors_origins = os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router, prefix="/v1")

    @app.exception_handler(PersonaEngineException)
    async def persona_engine_exception_handler(request: Request, exc: PersonaEngineException):
        logger.error(f"PersonaEngineException: {exc.message}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=exc.to_dict(),
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        # 排除 FastAPI 内置异常，避免覆盖默认的 422/404 等处理
        from fastapi import HTTPException
        from fastapi.exceptions import RequestValidationError
        if isinstance(exc, (HTTPException, RequestValidationError)):
            raise exc  # 让 FastAPI 默认处理器处理
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": "InternalServerError",
                "message": str(exc),
                "code": "INTERNAL_ERROR",
            },
        )

    @app.get("/")
    async def web_ui():
        html_path = Path(__file__).parent / "persona_engine" / "api" / "web_ui.html"
        if html_path.exists():
            return FileResponse(str(html_path))
        return {"message": "Web UI not found"}

    @app.get("/v1/health")
    async def health_check():
        from datetime import datetime
        db_healthy = await database.health_check()
        return {
            "status": "healthy" if db_healthy else "degraded",
            "database": "connected" if db_healthy else "disconnected",
            "timestamp": datetime.now().isoformat(),
        }

    @app.get("/v1/debug/tasks")
    async def debug_tasks():
        """调试端点：查看当前注册的任务"""
        from datetime import datetime
        return {
            "registered_tasks": task_registry.list_tasks(),
            "timestamp": datetime.now().isoformat(),
        }

    return app

if __name__ == "__main__":
    import asyncio
    app = get_app()
    uvicorn.run(app, host="127.0.0.1", port=8080, log_level="info")
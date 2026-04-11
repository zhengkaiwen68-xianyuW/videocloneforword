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
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base_dir = app_dir

sys.path.insert(0, base_dir)
os.chdir(base_dir)

# 设置环境变量让 SQLAlchemy 能找到模块
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse

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

        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")

        yield

        logger.info("Shutting down Persona Engine API Server...")
        # 取消所有后台任务
        task_registry.cancel_all()
        await asyncio.sleep(0.5)  # 给任务一些时间响应取消
        await database.close()
        logger.info("Shutdown complete")

    app = FastAPI(
        title="Persona Engine API",
        description="短视频人格深度重构与洗稿引擎 - 本地 API 接口",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
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
        html_path = Path(__file__).parent / "api" / "web_ui.html"
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
    app = get_app()
    uvicorn.run(app, host="127.0.0.1", port=8080, log_level="info")

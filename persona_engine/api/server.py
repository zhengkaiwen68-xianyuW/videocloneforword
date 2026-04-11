"""
FastAPI 服务入口

启动本地 API 服务器，开放接口供 .exe 调用
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse

from persona_engine.api.routes import router
from persona_engine.core.config import config
from persona_engine.core.exceptions import PersonaEngineException
from persona_engine.storage.database import database


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("Starting Persona Engine API Server...")

    # 初始化数据库表
    try:
        await database.create_tables()
        logger.info("Database tables initialized")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")

    yield

    # 关闭时
    logger.info("Shutting down Persona Engine API Server...")
    await database.close()


# 创建 FastAPI 应用
app = FastAPI(
    title="Persona Engine API",
    description="短视频人格深度重构与洗稿引擎 - 本地 API 接口",
    version="0.1.0",
    lifespan=lifespan,
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 注册路由
app.include_router(router, prefix="/v1")


# 全局异常处理
@app.exception_handler(PersonaEngineException)
async def persona_engine_exception_handler(request: Request, exc: PersonaEngineException):
    """处理自定义异常"""
    logger.error(f"PersonaEngineException: {exc.message}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content=exc.to_dict(),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """处理通用异常"""
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
    """Web UI 界面"""
    html_path = Path(__file__).parent / "web_ui.html"
    if html_path.exists():
        return FileResponse(str(html_path))
    return {"message": "Web UI not found"}


def run_server(host: str | None = None, port: int | None = None):
    """
    运行 API 服务器

    Args:
        host: 主机地址（默认从配置读取）
        port: 端口（默认从配置读取）
    """
    app_config = config.app

    host = host or app_config.host
    port = port or app_config.port

    logger.info(f"Starting server on {host}:{port}")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=True,
    )


# ========== CLI 入口 ==========

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Persona Engine API Server")
    parser.add_argument("--host", default=None, help="Host to bind")
    parser.add_argument("--port", type=int, default=None, help="Port to bind")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")

    args = parser.parse_args()

    if args.reload:
        # 开发模式
        import shutil
        if shutil.which("uvicorn"):
            os.system(f"uvicorn api.server:app --reload --host {args.host or '127.0.0.1'} --port {args.port or 8080}")
        else:
            logger.warning("uvicorn not found in PATH, using default server")
            run_server(args.host, args.port)
    else:
        run_server(args.host, args.port)

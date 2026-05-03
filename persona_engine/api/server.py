"""
FastAPI 服务兼容入口。

真正的应用构造逻辑集中在 main.get_app()，避免不同启动方式加载出
不同的中间件、生命周期钩子和调试端点。
"""

from __future__ import annotations

import logging

import uvicorn

from main import get_app
from persona_engine.core.config import config

logger = logging.getLogger(__name__)

app = get_app()


def run_server(host: str | None = None, port: int | None = None, reload: bool = False):
    """
    运行 API 服务器。

    Args:
        host: 主机地址（默认从配置读取）
        port: 端口（默认从配置读取）
        reload: 是否启用开发热重载
    """
    app_config = config.app
    bind_host = host or app_config.host
    bind_port = port or app_config.port

    logger.info("Starting server on %s:%s", bind_host, bind_port)

    if reload:
        uvicorn.run(
            "persona_engine.api.server:app",
            host=bind_host,
            port=bind_port,
            log_level="info",
            access_log=True,
            reload=True,
        )
        return

    uvicorn.run(
        app,
        host=bind_host,
        port=bind_port,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Persona Engine API Server")
    parser.add_argument("--host", default=None, help="Host to bind")
    parser.add_argument("--port", type=int, default=None, help="Port to bind")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")

    args = parser.parse_args()
    run_server(args.host, args.port, reload=args.reload)

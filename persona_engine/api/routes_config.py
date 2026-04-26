"""
配置管理与健康检查路由

GET /health                  健康检查
GET /config/bilibili         获取B站配置
PUT /config/bilibili         更新B站配置
GET /bilibili/space/preview  预览UP主空间
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException

from persona_engine.core.exceptions import BilibiliDownloadError
from persona_engine.asr.bilibili_downloader import (
    BilibiliSpaceDownloader,
    is_valid_bilibili_space_url,
    extract_uid_from_space_url,
)
from persona_engine.api.models import BilibiliConfigResponse, BilibiliConfigUpdateRequest

logger = logging.getLogger(__name__)
router = APIRouter()


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

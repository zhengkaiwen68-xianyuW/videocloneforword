"""
Bilibili 视频下载模块

使用 yt-dlp 下载 B站 视频并提取音频，支持：
- 多链接批量下载
- 请求间隔和重试机制（应对反爬）
- 视频信息获取
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import NamedTuple

from yt_dlp import YoutubeDL

from ..core.exceptions import BilibiliDownloadError, AudioExtractionError

logger = logging.getLogger(__name__)

# 视频分割标记（用于分隔多个视频的ASR结果）
VIDEO_SPLIT_MARKER = "|||BILI_ASR_SPLIT|||"


class DownloadStatus(Enum):
    """下载状态"""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class DownloadTask:
    """单个下载任务"""
    url: str
    status: DownloadStatus = DownloadStatus.PENDING
    progress: float = 0.0
    error: str | None = None
    audio_path: str | None = None
    title: str | None = None
    duration: float | None = None


@dataclass
class BatchDownloadResult:
    """批量下载结果"""
    tasks: list[DownloadTask]
    completed_count: int = 0
    failed_count: int = 0
    total_count: int = 0

    def get_all_texts(self) -> list[str]:
        """获取所有成功下载的视频ASR文本"""
        texts = []
        for task in self.tasks:
            if task.status == DownloadStatus.COMPLETED and task.audio_path:
                # 读取临时文件获取文本（由调用方填充）
                pass
        return texts


class BilibiliDownloader:
    """
    B站视频下载器

    使用 yt-dlp 提取视频音频，支持：
    - 多链接批量下载
    - 请求间隔和重试机制（应对反爬）
    - 进度回调
    - Cookie认证

    ==========================================================================
    B站反爬机制说明（统一优化入口）
    ==========================================================================
    参考项目: BBDown (https://github.com/nilaoda/BBDown)

    B站反爬限制:
    - 412: 请求被阻止，需要等待后重试
    - 429: 请求过于频繁
    - 403: 禁止访问，可能需要登录/Cookie

    当前实现优化（参考BBDown）:
    1. Cookie支持 - 配置中的 cookie 字段，提高下载成功率
    2. 指数退避重试 - 失败后等待时间指数增长 (retry_base_delay * 2^retry_count)
    3. 随机请求间隔 - min_interval ~ max_interval 之间随机
    4. User-Agent配置 - 从配置读取，可定期更新

    后续优化方向（TODO）:
    - 代理IP支持 - 添加代理池，避免单一IP被封
    - 多API模式切换 - Web/TV/App/国际版 (参考BBDown的-tv/-app/-intl)
    - WBI签名支持 - B站API需要WBI签名，后续可集成yt-dlp方案

    涉及此下载器的位置：
    - routes.py::bilibili_asr()           [POST /v1/asr/from-url]
    - routes.py::run_bilibili_asr_task()  [ASR后台任务]
    - routes.py::run_persona_from_videos_task()  [创建人格后台任务]
    - routes.py::run_persona_upgrade_task() [追加视频后台任务]
    ==========================================================================
    """

    def __init__(
        self,
        download_dir: str | None = None,
        min_interval: float | None = None,
        max_interval: float | None = None,
        max_retries: int | None = None,
        retry_base_delay: float | None = None,
        cookie: str | None = None,
        user_agent: str | None = None,
    ):
        """
        初始化下载器

        Args:
            download_dir: 下载目录，默认使用系统临时目录
            min_interval: 最小请求间隔（秒），默认从配置读取
            max_interval: 最大请求间隔（秒），默认从配置读取
            max_retries: 最大重试次数，默认从配置读取
            retry_base_delay: 指数退避基数(秒)，默认从配置读取
            cookie: Cookie认证字符串，默认从配置读取
            user_agent: User-Agent字符串，默认从配置读取
        """
        # 尝试从配置读取
        try:
            from ..core.config import config
            bili_cfg = config.bilibili
            self.min_interval = min_interval if min_interval is not None else bili_cfg.min_interval
            self.max_interval = max_interval if max_interval is not None else bili_cfg.max_interval
            self.max_retries = max_retries if max_retries is not None else bili_cfg.max_retries
            self.retry_base_delay = retry_base_delay if retry_base_delay is not None else bili_cfg.retry_base_delay
            self.cookie = cookie if cookie is not None else bili_cfg.cookie
            self.user_agent = user_agent if user_agent is not None else bili_cfg.user_agent
        except Exception:
            # 配置不可用时使用默认值
            self.min_interval = min_interval if min_interval is not None else 3.0
            self.max_interval = max_interval if max_interval is not None else 10.0
            self.max_retries = max_retries if max_retries is not None else 5
            self.retry_base_delay = retry_base_delay if retry_base_delay is not None else 2.0
            self.cookie = cookie or ""
            self.user_agent = user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

        self.download_dir = Path(download_dir) if download_dir else Path(tempfile.gettempdir()) / "persona_engine_bili"
        self.download_dir.mkdir(parents=True, exist_ok=True)

        # 用户自定义的请求间隔（如果需要）
        self._last_request_time = 0.0

    def _get_random_interval(self) -> float:
        """获取随机请求间隔"""
        return random.uniform(self.min_interval, self.max_interval)

    async def _wait_interval(self) -> None:
        """等待请求间隔"""
        interval = self._get_random_interval()
        await asyncio.sleep(interval)

    async def _exponential_backoff(self, retry_count: int, base_delay: float | None = None) -> float:
        """
        计算指数退避等待时间

        参考BBDown的重试机制设计

        Args:
            retry_count: 当前重试次数
            base_delay: 基础延迟秒数，默认 self.retry_base_delay

        Returns:
            等待秒数
        """
        base = base_delay or self.retry_base_delay
        # 指数退避: base * 2^retry_count + 随机波动
        wait_time = base * (2 ** retry_count) + random.uniform(0, base)
        # 最大不超过60秒
        return min(wait_time, 60.0)

    async def download_and_extract_audio(
        self,
        url: str,
        progress_callback: callable | None = None,
        retry_count: int = 0,
    ) -> str:
        """
        下载B站视频并提取音频

        Args:
            url: B站视频链接
            progress_callback: 进度回调函数 (progress: float, status: str)
            retry_count: 当前重试次数

        Returns:
            提取的音频文件路径 (mp3格式)

        Raises:
            BilibiliDownloadError: 下载失败
            AudioExtractionError: 音频提取失败
        """
        try:
            # 请求间隔
            await self._wait_interval()

            task_id = f"bili_{int(time.time() * 1000)}"
            output_dir = self.download_dir / task_id
            output_dir.mkdir(parents=True, exist_ok=True)

            audio_path = output_dir / "audio.mp3"

            # yt-dlp 配置 - 增强反爬
            # 参考BBDown: https://github.com/nilaoda/BBDown
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': str(output_dir / 'video'),
                'quiet': True,
                'no_warnings': True,
                'extract_audio': True,
                'audio_format': 'mp3',
                'audio Quality': '5',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                # 反爬相关配置 - 使用配置中的User-Agent
                'http_headers': {
                    'User-Agent': self.user_agent,
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    'Referer': 'https://www.bilibili.com',
                },
            }

            # 添加Cookie认证（参考BBDown的 -c, --cookie 选项）
            if self.cookie:
                ydl_opts['http_headers']['Cookie'] = self.cookie

            if progress_callback:
                def progress_hook(d):
                    if d['status'] == 'downloading':
                        total = d.get('total_bytes', 0) or d.get('total_bytes_estimate', 0)
                        downloaded = d.get('downloaded_bytes', 0)
                        if total > 0:
                            progress = (downloaded / total) * 100
                            progress_callback(progress, f"下载中... {progress:.1f}%")
                    elif d['status'] == 'finished':
                        progress_callback(95, "提取音频中...")

                ydl_opts['progress_hooks'] = [progress_hook]

            if progress_callback:
                progress_callback(0, "开始下载...")

            # 在线程池中执行下载
            loop = asyncio.get_event_loop()
            video_info = await loop.run_in_executor(
                None, self._download_with_retry, url, ydl_opts, output_dir
            )

            if progress_callback:
                progress_callback(100, "下载完成")

            # 查找生成的音频文件
            audio_files = list(output_dir.glob("*.mp3"))
            if not audio_files:
                audio_files = list(output_dir.glob("*.wav"))
                audio_files.extend(output_dir.glob("*.m4a"))
                audio_files.extend(output_dir.glob("*.flac"))

            if not audio_files:
                raise AudioExtractionError(
                    message="Failed to extract audio from video",
                    details={"output_dir": str(output_dir)},
                )

            # 复制到目标位置
            final_audio_path = output_dir / "audio.mp3"
            shutil.copy(str(audio_files[0]), str(final_audio_path))

            # 返回音频路径和视频信息
            self._last_downloaded_info = {
                'audio_path': str(final_audio_path),
                'title': video_info.get('title') if video_info else None,
                'duration': video_info.get('duration') if video_info else None,
            }

            return str(final_audio_path)

        except BilibiliDownloadError:
            raise
        except AudioExtractionError:
            raise
        except Exception as e:
            error_str = str(e)
            # 检查是否应该重试
            if retry_count < self.max_retries and self._is_retryable_error(error_str):
                # 指数退避等待（参考BBDown的重试机制）
                wait_time = await self._exponential_backoff(retry_count)
                logger.warning(
                    f"Download failed (412/429可能), retrying ({retry_count + 1}/{self.max_retries}) "
                    f"after {wait_time:.1f}s: {error_str}"
                )
                await asyncio.sleep(wait_time)
                return await self.download_and_extract_audio(
                    url, progress_callback, retry_count + 1
                )
            raise BilibiliDownloadError(
                message=f"Bilibili download failed: {error_str}",
                url=url,
                details={"error_type": type(e).__name__, "retry_count": retry_count},
            )

    def _is_retryable_error(self, error: str) -> bool:
        """判断错误是否可重试"""
        retryable_patterns = [
            'timeout',
            'connection',
            'network',
            '429',
            '403',
            'banned',
            'frequency',
        ]
        error_lower = error.lower()
        return any(pattern in error_lower for pattern in retryable_patterns)

    def _download_with_retry(self, url: str, ydl_opts: dict, output_dir: Path) -> dict | None:
        """
        执行下载（支持重试）

        Returns:
            视频信息字典
        """
        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                logger.info(f"Downloaded video: {info.get('title', 'unknown')}")
                return {
                    'title': info.get('title'),
                    'duration': info.get('duration'),
                }
        except Exception as e:
            logger.error(f"Download error: {e}")
            raise BilibiliDownloadError(
                message=f"Failed to download video: {str(e)}",
                url=url,
            )

    async def get_video_info(self, url: str) -> dict:
        """
        获取视频信息（不下载）

        Args:
            url: B站视频链接

        Returns:
            视频信息字典
        """
        await self._wait_interval()

        loop = asyncio.get_event_loop()

        def _extract_info():
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Referer': 'https://www.bilibili.com',
                },
            }
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return {
                    'title': info.get('title', ''),
                    'duration': info.get('duration', 0),
                    'uploader': info.get('uploader', ''),
                    'description': info.get('description', ''),
                    'view_count': info.get('view_count', 0),
                    'like_count': info.get('like_count', 0),
                }

        return await loop.run_in_executor(None, _extract_info)

    def cleanup(self, audio_path: str) -> None:
        """
        清理临时文件

        Args:
            audio_path: 音频文件路径
        """
        try:
            audio_file = Path(audio_path)
            task_dir = audio_file.parent
            if task_dir.exists() and task_dir.parent == self.download_dir:
                shutil.rmtree(task_dir)
        except Exception as e:
            logger.warning(f"Failed to cleanup temp files: {e}")

    def cleanup_all(self) -> None:
        """清理所有临时文件"""
        try:
            if self.download_dir.exists():
                shutil.rmtree(self.download_dir)
                self.download_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"Failed to cleanup all temp files: {e}")


def is_valid_bilibili_url(url: str) -> bool:
    """
    验证是否为有效的B站视频链接

    Args:
        url: 待验证的URL

    Returns:
        是否为有效B站链接
    """
    import re

    # 清理空白
    url = url.strip()
    if not url:
        return False

    # B站视频链接格式
    valid_patterns = [
        r'https?://www\.bilibili\.com/video/BV[\w]+',
        r'https?://b23\.tv/[\w]+',
        r'https?://bilibili\.com/video/BV[\w]+',
        r'BV[\w]+',  # 纯BV号
    ]

    for pattern in valid_patterns:
        if re.match(pattern, url):
            return True
    return False


def parse_multiple_urls(text: str) -> list[str]:
    """
    从多行文本中解析出所有有效的B站链接

    Args:
        text: 包含多个链接的文本（每行一个）

    Returns:
        有效的B站链接列表
    """
    lines = text.strip().split('\n')
    urls = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 如果是纯BV号，补全为URL
        if line.startswith('BV') and '/' not in line:
            line = f'https://www.bilibili.com/video/{line}'

        if is_valid_bilibili_url(line):
            urls.append(line)

    return urls


# ========== B站UP主空间相关函数 ==========

class SpaceVideoInfo(NamedTuple):
    """UP主空间视频信息"""
    bv_id: str          # BV号
    title: str          # 标题
    duration: float     # 时长（秒）
    pubdate: float      # 发布时间戳


class BilibiliSpaceDownloader:
    """
    B站UP主空间视频列表获取器

    使用 yt-dlp 的 BilibiliSpaceVideoIE 提取器获取UP主空间视频列表，
    不下载视频，只获取视频元信息。

    ==========================================================================
    B站反爬机制说明（统一优化入口）
    ==========================================================================
    参考项目: BBDown (https://github.com/nilaoda/BBDown)

    获取空间视频列表会触发B站更严格的反爬限制：
    - 412: 请求被阻止（最常见），通常需要等待30-60秒后重试
    - 需要WBI签名：空间API使用WBI签名保护，yt-dlp已内置实现

    当前实现优化（参考BBDown）:
    1. 指数退避重试 - 失败后等待时间指数增长
    2. Cookie支持 - 配置登录Cookie可获取更完整的视频列表
    3. 从配置读取请求间隔 - 统一下载器配置管理

    后续优化方向（TODO）:
    - 缓存机制 - 空间视频列表缓存，避免重复请求
    - WBI签名优化 - yt-dlp版本更新时同步WBI签名算法

    此下载器被以下入口调用：
    - routes.py::create_persona() [处理 space_url 参数时]
    ==========================================================================
    """

    def __init__(
        self,
        min_interval: float | None = None,
        max_interval: float | None = None,
        max_retries: int | None = None,
        retry_base_delay: float | None = None,
        cookie: str | None = None,
        user_agent: str | None = None,
    ):
        """
        初始化空间视频获取器

        Args:
            min_interval: 最小请求间隔（秒）
            max_interval: 最大请求间隔（秒）
            max_retries: 最大重试次数
            retry_base_delay: 指数退避基数(秒)
            cookie: Cookie认证字符串
            user_agent: User-Agent字符串
        """
        # 尝试从配置读取
        try:
            from ..core.config import config
            bili_cfg = config.bilibili
            self.min_interval = min_interval if min_interval is not None else bili_cfg.min_interval
            self.max_interval = max_interval if max_interval is not None else bili_cfg.max_interval
            self.max_retries = max_retries if max_retries is not None else bili_cfg.max_retries
            self.retry_base_delay = retry_base_delay if retry_base_delay is not None else bili_cfg.retry_base_delay
            self.cookie = cookie if cookie is not None else bili_cfg.cookie
            self.user_agent = user_agent if user_agent is not None else bili_cfg.user_agent
        except Exception:
            # 配置不可用时使用默认值
            self.min_interval = min_interval if min_interval is not None else 3.0
            self.max_interval = max_interval if max_interval is not None else 10.0
            self.max_retries = max_retries if max_retries is not None else 5
            self.retry_base_delay = retry_base_delay if retry_base_delay is not None else 2.0
            self.cookie = cookie or ""
            self.user_agent = user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    def _get_random_interval(self) -> float:
        """获取随机请求间隔"""
        return random.uniform(self.min_interval, self.max_interval)

    async def _wait_interval(self) -> None:
        """等待请求间隔"""
        interval = self._get_random_interval()
        await asyncio.sleep(interval)

    def _exponential_backoff(self, retry_count: int) -> float:
        """
        计算指数退避等待时间

        Args:
            retry_count: 当前重试次数

        Returns:
            等待秒数
        """
        wait_time = self.retry_base_delay * (2 ** retry_count) + random.uniform(0, self.retry_base_delay)
        return min(wait_time, 60.0)

    def _get_headers(self) -> dict:
        """获取HTTP头（参考BBDown的 -c, --cookie 选项）"""
        headers = {
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'https://www.bilibili.com',
        }
        if self.cookie:
            headers['Cookie'] = self.cookie
        return headers

    async def get_uploader_videos(
        self,
        uid: str,
        limit: int = 30,
        progress_callback: callable | None = None,
        retry_count: int = 0,
    ) -> list[SpaceVideoInfo]:
        """
        获取UP主空间最新发布的视频列表

        Args:
            uid: UP主的 UID (space.bilibili.com/UID 中的数字)
            limit: 获取数量上限，默认30
            progress_callback: 进度回调 (progress: float, status: str)
            retry_count: 当前重试次数（内部使用）

        Returns:
            SpaceVideoInfo 列表，按发布时间倒序（最新在前）

        Raises:
            BilibiliDownloadError: 获取失败
        """
        await self._wait_interval()

        loop = asyncio.get_event_loop()

        def _fetch():
            space_url = f"https://space.bilibili.com/{uid}/video"
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,  # 只获取信息，不下载
                'playlist_items': f'1-{limit}',  # 限制数量
                'http_headers': self._get_headers(),
            }

            try:
                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(space_url, download=False)

                    if not info or 'entries' not in info:
                        raise BilibiliDownloadError(
                            message=f"Failed to get space videos for UID {uid}",
                            details={"uid": uid},
                        )

                    videos = []
                    for entry in info['entries']:
                        if entry is None:
                            continue
                        # 提取BV号（yt-dlp返回的ID可能是完整URL或BV号）
                        bv_id = entry.get('id', '')
                        if not bv_id.startswith('BV'):
                            # 如果不是BV号，尝试从URL提取
                            webpage_url = entry.get('webpage_url', '')
                            bv_match = re.search(r'BV[\w]+', webpage_url)
                            if bv_match:
                                bv_id = bv_match.group(0)
                            else:
                                continue

                        videos.append(SpaceVideoInfo(
                            bv_id=bv_id,
                            title=entry.get('title', '未知标题'),
                            duration=float(entry.get('duration', 0)),
                            pubdate=float(entry.get('epoch', 0)),
                        ))

                    # 按发布时间倒序（最新在前）
                    videos.sort(key=lambda x: x.pubdate, reverse=True)

                    return videos

            except Exception as e:
                error_str = str(e)
                # 检查是否可重试 (412/429/403)
                if retry_count < self.max_retries and ('412' in error_str or '429' in error_str or '403' in error_str):
                    # 指数退避等待后重试
                    wait_time = self._exponential_backoff(retry_count)
                    logger.warning(
                        f"Space API rate limited (412/429), retrying ({retry_count + 1}/{self.max_retries}) "
                        f"after {wait_time:.1f}s: {error_str}"
                    )
                    raise BilibiliDownloadError(
                        message=f"Bilibili API rate limited. Retrying after {wait_time:.1f}s...",
                        details={"uid": uid, "error": error_str, "retry_after": wait_time},
                        retryable=True,
                    )
                raise BilibiliDownloadError(
                    message=f"Failed to get space videos: {error_str}",
                    details={"uid": uid},
                )

        if progress_callback:
            progress_callback(0, "正在获取视频列表...")

        try:
            videos = await loop.run_in_executor(None, _fetch)
        except BilibiliDownloadError as e:
            # 如果是可重试的错误，尝试指数退避重试
            if getattr(e, 'retryable', False) and retry_count < self.max_retries:
                await asyncio.sleep(e.details.get('retry_after', 30))
                return await self.get_uploader_videos(uid, limit, progress_callback, retry_count + 1)
            raise

        if progress_callback:
            progress_callback(100, f"获取到 {len(videos)} 个视频")

        return videos


def is_valid_bilibili_space_url(url: str) -> bool:
    """
    验证是否为有效的B站个人空间链接

    Args:
        url: 待验证的URL

    Returns:
        是否为有效B站个人空间链接
    """
    # 清理空白
    url = url.strip()
    if not url:
        return False

    # B站个人空间链接格式
    valid_patterns = [
        r'https?://space\.bilibili\.com/\d+',
        r'https?://space\.bilibili\.com/\d+/video',
    ]

    for pattern in valid_patterns:
        if re.match(pattern, url):
            return True
    return False


def extract_uid_from_space_url(url: str) -> str | None:
    """
    从空间链接提取UID

    Args:
        url: B站个人空间链接

    Returns:
        UID字符串，如果解析失败返回None
    """
    # 清理空白
    url = url.strip()

    # 支持的格式:
    # - https://space.bilibili.com/12345678
    # - https://space.bilibili.com/12345678/
    # - https://space.bilibili.com/12345678/video
    match = re.search(r'space\.bilibili\.com/(\d+)', url)
    if match:
        return match.group(1)
    return None


def build_video_url_from_bv(bv_id: str) -> str:
    """
    从 BV 号构建完整视频链接

    Args:
        bv_id: BV号

    Returns:
        完整的B站视频URL
    """
    # 清理BV号
    bv_id = bv_id.strip()
    if not bv_id.startswith('BV'):
        bv_id = 'BV' + bv_id
    return f"https://www.bilibili.com/video/{bv_id}"

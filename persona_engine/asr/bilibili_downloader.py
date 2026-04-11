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
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

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
    """

    # 默认请求间隔（秒），防止频繁请求被封
    DEFAULT_MIN_INTERVAL = 2.0
    DEFAULT_MAX_INTERVAL = 5.0
    # 最大重试次数
    MAX_RETRIES = 3

    def __init__(
        self,
        download_dir: str | None = None,
        min_interval: float | None = None,
        max_interval: float | None = None,
        max_retries: int | None = None,
    ):
        """
        初始化下载器

        Args:
            download_dir: 下载目录，默认使用系统临时目录
            min_interval: 最小请求间隔（秒）
            max_interval: 最大请求间隔（秒）
            max_retries: 最大重试次数
        """
        self.download_dir = Path(download_dir) if download_dir else Path(tempfile.gettempdir()) / "persona_engine_bili"
        self.download_dir.mkdir(parents=True, exist_ok=True)

        self.min_interval = min_interval or self.DEFAULT_MIN_INTERVAL
        self.max_interval = max_interval or self.DEFAULT_MAX_INTERVAL
        self.max_retries = max_retries or self.MAX_RETRIES

        # 用户自定义的请求间隔（如果需要）
        self._last_request_time = 0.0

    def _get_random_interval(self) -> float:
        """获取随机请求间隔"""
        return random.uniform(self.min_interval, self.max_interval)

    async def _wait_interval(self) -> None:
        """等待请求间隔"""
        interval = self._get_random_interval()
        await asyncio.sleep(interval)

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
                # 反爬相关配置
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    'Referer': 'https://www.bilibili.com',
                },
                # Cookie支持（可选，需要用户配置）
                # 'cookiefile': 'cookies.txt',
            }

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
                logger.warning(f"Download failed, retrying ({retry_count + 1}/{self.max_retries}): {error_str}")
                await asyncio.sleep(random.uniform(5, 10))  # 重试前等待
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

"""
共享依赖实例

所有路由模块和后台任务共用的仓储、服务单例。
集中管理生命周期，避免重复实例化。
"""

import logging

from persona_engine.core.task_registry import task_registry
from persona_engine.core.concurrency import concurrency_limiter
from persona_engine.storage.persona_repo import PersonaRepository, TaskRepository, VideoTaskRepository
from persona_engine.core.exceptions import TranscriptionError

logger = logging.getLogger(__name__)

# ── 仓储实例 ──
persona_repo = PersonaRepository()
task_repo = TaskRepository()
video_task_repo = VideoTaskRepository()

class LazyWhisperTranscriber:
    """按需加载 Whisper 转写器，避免非 ASR 路由被重依赖阻塞。"""

    def __init__(self):
        self._instance = None

    def _get_instance(self):
        if self._instance is None:
            try:
                from persona_engine.asr.transcriber import WhisperTranscriber
            except ModuleNotFoundError as e:
                if e.name == "faster_whisper":
                    raise TranscriptionError(
                        "ASR dependency faster-whisper is not installed. "
                        "Install requirements.txt and ensure FFmpeg/libav development libraries are available."
                    ) from e
                raise
            self._instance = WhisperTranscriber()
        return self._instance

    async def transcribe_async(self, *args, **kwargs):
        return await self._get_instance().transcribe_async(*args, **kwargs)


# ── 服务单例 ──
_transcriber = LazyWhisperTranscriber()

# ── 并发控制 ──
concurrency = concurrency_limiter

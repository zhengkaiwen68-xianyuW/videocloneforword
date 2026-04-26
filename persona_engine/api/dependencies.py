"""
共享依赖实例

所有路由模块和后台任务共用的仓储、服务单例。
集中管理生命周期，避免重复实例化。
"""

import logging

from persona_engine.core.task_registry import task_registry
from persona_engine.core.concurrency import concurrency_limiter
from persona_engine.storage.persona_repo import PersonaRepository, TaskRepository, VideoTaskRepository
from persona_engine.asr.transcriber import WhisperTranscriber

logger = logging.getLogger(__name__)

# ── 仓储实例 ──
persona_repo = PersonaRepository()
task_repo = TaskRepository()
video_task_repo = VideoTaskRepository()

# ── 服务单例 ──
# WhisperTranscriber 实例本身轻量；模型常驻 WhisperWorker 子进程，懒加载
_transcriber = WhisperTranscriber()

# ── 并发控制 ──
concurrency = concurrency_limiter

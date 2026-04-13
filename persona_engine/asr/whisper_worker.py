"""
Whisper 单例进程池

设计目标：
1. 模型常驻子进程，避免每视频重复加载（large-v3 约 3GB VRAM，每次加载 5-10 秒）
2. 取消时重启进程池，物理回收 VRAM（asyncio.to_thread 无法真正打断线程）
3. 通过 task_registry 实现协程层面的取消信号轮询

架构原理：
- ProcessPoolExecutor(max_workers=1) + spawn 上下文
  spawn 模式确保 CUDA 上下文与父进程完全隔离（Windows/Linux 通用）
- _worker_initializer 在子进程启动时加载一次模型，此后常驻
- 取消时调用 _restart_executor：直接 terminate() 子进程 + 重建 executor
  操作系统会强制回收该进程持有的所有 VRAM
"""

import asyncio
import logging
import multiprocessing
from concurrent.futures import ProcessPoolExecutor

logger = logging.getLogger(__name__)


# =====================================================
# 子进程全局状态（模型常驻内存，随进程生命周期存在）
# =====================================================

_worker_model = None
_worker_config: dict | None = None


def _worker_initializer(config_dict: dict) -> None:
    """
    子进程初始化函数：加载 Whisper 模型并常驻。

    此函数由 ProcessPoolExecutor 在子进程启动时自动调用一次。
    之后每次调用 _worker_transcribe 都直接复用已加载的模型，
    不再重复从磁盘加载（large-v3 约 5-10 秒 / 3GB VRAM）。
    """
    global _worker_model, _worker_config
    import logging as _logging

    _logging.basicConfig(level=_logging.INFO)
    _worker_logger = _logging.getLogger(__name__)

    try:
        from faster_whisper import WhisperModel

        _worker_config = config_dict
        _worker_model = WhisperModel(
            model_size_or_path=config_dict["model_size"],
            device=config_dict["device"],
            compute_type=config_dict["compute_type"],
        )
        _worker_logger.info(
            f"[WhisperWorker] 模型已加载: {config_dict['model_size']} "
            f"on {config_dict['device']} ({config_dict['compute_type']})"
        )
    except Exception as e:
        _worker_logger.error(f"[WhisperWorker] 模型加载失败: {e}")
        raise


def _worker_transcribe(audio_path: str) -> dict:
    """
    在子进程中执行 Whisper 推理（模型已常驻，直接推理）。

    此函数必须是模块级函数（不能嵌套），以保证 multiprocessing spawn
    模式下的 pickle 序列化正常工作。

    Returns:
        dict 包含 text, words, language, duration, speech_duration
    """
    global _worker_model, _worker_config

    if _worker_model is None or _worker_config is None:
        raise RuntimeError("Whisper worker not initialized")

    cfg = _worker_config
    segments, info = _worker_model.transcribe(
        audio_path,
        language=cfg["language"],
        vad_filter=cfg["vad_filter"],
        vad_parameters=cfg["vad_parameters"],
        word_timestamps=cfg["word_timestamps"],
    )

    text_parts: list[str] = []
    words_data: list[dict] = []
    total_speech_duration = 0.0

    for segment in segments:
        if segment.text:
            text_parts.append(segment.text.strip())
        if segment.words:
            for word in segment.words:
                words_data.append({
                    "word": word.word.strip(),
                    "start": word.start,
                    "end": word.end,
                })
                total_speech_duration += word.end - word.start

    return {
        "text": " ".join(text_parts),
        "words": words_data,
        "language": info.language,
        "duration": info.duration or (words_data[-1]["end"] if words_data else 0.0),
        "speech_duration": total_speech_duration,
    }


# =====================================================
# WhisperWorker 单例管理类
# =====================================================

class WhisperWorker:
    """
    Whisper 进程池单例管理器

    - 懒加载：首次调用 transcribe 时才启动子进程并加载模型
    - 常驻：模型加载后在子进程中常驻，直到显式重启
    - 取消安全：取消时 terminate() 子进程，操作系统强制回收 VRAM
    """

    _instance: "WhisperWorker | None" = None

    def __new__(cls) -> "WhisperWorker":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._executor: ProcessPoolExecutor | None = None
            cls._instance._config_dict: dict | None = None
        return cls._instance

    def _build_config_dict(self) -> dict:
        """从全局配置构建可 pickle 的字典（用于传递给子进程）"""
        from persona_engine.core.config import config
        w = config.whisper
        return {
            "model_size": w.model_size,
            "device": w.device,
            "compute_type": w.compute_type,
            "language": w.language,
            "vad_filter": w.vad_filter,
            "vad_parameters": w.vad_parameters,
            "word_timestamps": w.word_timestamps,
        }

    def _ensure_executor(self) -> ProcessPoolExecutor:
        """懒加载：首次调用时创建进程池并启动子进程（加载模型）"""
        if self._executor is None:
            self._config_dict = self._build_config_dict()
            ctx = multiprocessing.get_context("spawn")
            self._executor = ProcessPoolExecutor(
                max_workers=1,
                mp_context=ctx,
                initializer=_worker_initializer,
                initargs=(self._config_dict,),
            )
            logger.info(
                f"[WhisperWorker] 进程池启动，模型正在子进程中加载: "
                f"{self._config_dict['model_size']} / {self._config_dict['device']}"
            )
        return self._executor

    def _restart_executor(self) -> None:
        """
        重启进程池：物理终止子进程，强制释放 VRAM。

        用于任务取消或超时场景。进程被 OS 回收后，
        CUDA 上下文随之销毁，VRAM 立即归还给系统。
        """
        if self._executor is not None:
            # 直接 terminate() 子进程，确保 CUDA 上下文被彻底销毁
            try:
                for process in self._executor._processes.values():
                    process.terminate()
            except Exception as e:
                logger.warning(f"[WhisperWorker] 终止子进程时出错（可忽略）: {e}")

            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
            logger.info("[WhisperWorker] 进程池已重启，VRAM 已释放")

    async def transcribe(self, audio_path: str, task_id: str) -> dict | None:
        """
        异步推理，每秒轮询一次取消信号。

        当检测到 task_registry 取消标志时，重启进程池物理释放 VRAM。
        当父协程被 asyncio.wait_for 超时取消时，同样触发重启。

        Args:
            audio_path: 已下载的音频文件路径
            task_id: 任务 ID（对应 task_registry 中注册的 key）

        Returns:
            推理结果字典，取消时返回 None
        """
        from persona_engine.core.task_registry import task_registry

        loop = asyncio.get_running_loop()
        executor = self._ensure_executor()
        future = loop.run_in_executor(executor, _worker_transcribe, audio_path)

        try:
            while not future.done():
                if task_registry.is_cancelled(task_id):
                    logger.info(
                        f"[WhisperWorker][{task_id}] 检测到取消信号，"
                        "终止子进程并释放 VRAM"
                    )
                    future.cancel()
                    self._restart_executor()
                    return None
                await asyncio.sleep(1.0)

            return future.result()

        except asyncio.CancelledError:
            # asyncio.wait_for 超时或父协程被取消时触发
            logger.info(
                f"[WhisperWorker][{task_id}] 协程被取消（超时或外部取消），"
                "终止子进程并释放 VRAM"
            )
            future.cancel()
            self._restart_executor()
            return None

        except Exception as e:
            logger.error(f"[WhisperWorker][{task_id}] 推理失败: {e}")
            raise


# 全局单例（懒加载，首次 transcribe 调用时才真正启动子进程）
whisper_worker = WhisperWorker()

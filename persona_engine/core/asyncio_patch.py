"""
统一的 asyncio patch 模块

解决 yt-dlp 等库在没有 running loop 的线程中调用 asyncio.get_event_loop() 的问题。
在项目入口处统一执行一次，避免多处 patch 导致的冲突。
"""
import asyncio
import logging
import threading

logger = logging.getLogger(__name__)

_asyncio_loop: asyncio.AbstractEventLoop | None = None
_asyncio_loop_thread: threading.Thread | None = None
_asyncio_loop_lock = threading.Lock()


def _run_loop_forever():
    asyncio.set_event_loop(_asyncio_loop)
    _asyncio_loop.run_forever()


def _start_global_asyncio_loop():
    """启动全局 asyncio 事件循环（在后台线程中运行）"""
    global _asyncio_loop, _asyncio_loop_thread

    if _asyncio_loop is not None and _asyncio_loop.is_running():
        return

    with _asyncio_loop_lock:
        if _asyncio_loop is not None:
            return
        _asyncio_loop = asyncio.new_event_loop()
        _asyncio_loop_thread = threading.Thread(target=_run_loop_forever, daemon=True)
        _asyncio_loop_thread.start()
        logger.info("Global asyncio loop started in background thread")


# 保存原始函数
_original_get_running_loop = asyncio.get_running_loop
_original_get_event_loop = asyncio.get_event_loop


def _patched_get_running_loop():
    """返回全局 loop（模拟有 running loop）"""
    return _asyncio_loop


def _patched_get_event_loop():
    try:
        return _original_get_running_loop()
    except RuntimeError:
        # 没有 running loop，返回我们的全局 loop
        return _asyncio_loop


def apply_patch():
    """应用 asyncio patch（只执行一次）"""
    _start_global_asyncio_loop()
    asyncio.get_running_loop = _patched_get_running_loop
    asyncio.get_event_loop = _patched_get_event_loop
    logger.info("asyncio patch applied")


def get_global_loop() -> asyncio.AbstractEventLoop:
    """获取全局 asyncio loop 引用"""
    return _asyncio_loop

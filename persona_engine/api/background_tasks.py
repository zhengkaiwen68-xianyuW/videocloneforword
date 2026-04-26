"""
后台任务函数

所有 asyncio.create_task 启动的长运行函数集中管理。
路由模块只负责调用这些函数，不包含任务逻辑。

任务清单：
- run_rewrite_task()                             ← 重写迭代
- run_bilibili_asr_task()                        ← B站 ASR 批量处理
- _run_persona_from_videos_task_with_tracking()   ← 人格创建包装器
- run_persona_from_videos_task()                 ← 人格创建核心逻辑
- _run_persona_upgrade_task_with_tracking()      ← 人格升级包装器
- run_persona_upgrade_task()                     ← 人格升级核心逻辑
- _update_persona_progress()                     ← 进度更新辅助
"""

import asyncio
import logging
import os
import re as regex_module
from datetime import datetime

from persona_engine.core.task_registry import task_registry
from persona_engine.api.dependencies import persona_repo, task_repo, video_task_repo, _transcriber, concurrency
from persona_engine.asr.personality_extractor import PersonalityExtractor
from persona_engine.asr.bilibili_downloader import BilibiliDownloader, VIDEO_SPLIT_MARKER

logger = logging.getLogger(__name__)


# ==================== 重写任务 ====================

async def run_rewrite_task(
    task_id: str,
    source_text: str,
    persona_ids: list[str],
    locked_terms: list[str],
    max_iterations: int,
    timeout_seconds: int,
):
    """
    后台执行重写任务

    完整流程：人格注入 → MiniMax 重写 → 审计评分 → 迭代优化
    """
    from persona_engine.llm.factory import create_llm_provider
    from persona_engine.rewrite.persona_injector import PersonaInjector
    from persona_engine.audit.reverse_agent import ReverseAgent
    from persona_engine.audit.scorer import ConsistencyScorer
    from persona_engine.audit.iteration_controller import IterationController

    try:
        # 获取人格画像
        personas = await persona_repo.get_by_ids(persona_ids)
        if not personas:
            await task_repo.complete(task_id, status="failed", error_message="No personas found")
            return

        # 初始化组件
        minimax = create_llm_provider()
        injector = PersonaInjector(minimax)
        reverse_agent = ReverseAgent(minimax)
        scorer = ConsistencyScorer(reverse_agent)
        controller = IterationController(
            task_id=task_id,
            max_iterations=max_iterations,
            timeout_seconds=timeout_seconds,
        )

        controller.start()

        # 迭代重写
        while controller.should_continue():
            # 人格注入重写
            result = await injector.inject(
                source_text=source_text,
                persona_profile=personas[0],  # 目前单人格
                locked_terms=locked_terms,
            )

            rewritten_text = result["rewritten_text"]

            # 评分
            score_result = await scorer.score(
                rewritten_text=rewritten_text,
                original_profile=personas[0],
                locked_terms=locked_terms,
            )

            # ========== 术语硬熔断处理 ==========
            # 如果术语保护失败，不记录此版本，立即触发重写
            if score_result.get("status") == "FAIL_TERM_PROTECTION":
                logger.warning(
                    f"Task {task_id}: 术语保护失败 ({score_result.get('reason')})，立即重写"
                )
                # 记录失败信息但不参与评分比较
                await task_repo.update_result(
                    task_id=task_id,
                    best_text="[术语保护失败]",
                    best_score=0.0,
                    best_iteration=controller.state.iteration + 1,
                    history_versions=[{
                        "status": "FAIL_TERM_PROTECTION",
                        "reason": score_result.get("reason"),
                        "iteration": controller.state.iteration + 1,
                    }],
                    status="running",
                )
                continue  # 不调用 evaluate_and_record，直接进入下一轮

            current_score = score_result["total_score"]

            # 评估并记录（只有通过术语硬检查才进入此处）
            await controller.evaluate_and_record(
                rewritten_text=rewritten_text,
                score=current_score,
                metadata=score_result,
            )

            # 更新任务进度
            history_data = [
                {
                    "version": v.version,
                    "score": v.consistency_score,
                    "iteration": v.iteration,
                }
                for v in controller.state.history
            ]
            await task_repo.update_result(
                task_id=task_id,
                best_text=controller.state.best_text,
                best_score=controller.state.best_score,
                best_iteration=controller.state.best_iteration,
                history_versions=history_data,
                status="running",
            )

        # 完成任务
        best = controller.get_best_result()
        await task_repo.complete(
            task_id=task_id,
            status="completed" if best["score"] >= 90 else "completed_below_threshold",
        )

        logger.info(f"Task {task_id} completed with score {best['score']:.2f}")

    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}")
        await task_repo.complete(task_id, status="failed", error_message=str(e))


# ==================== B站 ASR 任务 ====================

async def run_bilibili_asr_task(task_id: str, urls: list[str], name: str | None):
    """
    后台执行B站视频批量下载和ASR

    ==========================================================================
    B站下载入口 #2 - ASR后台任务（被 bilibili_asr 调用）
    ==========================================================================
    调用链: run_bilibili_asr_task() -> BilibiliDownloader.download_and_extract_audio()
    反爬风险: 中等（批量请求，建议添加请求间隔）

    进度追踪: 通过 task_repo.update_result() 更新 history_versions
    统一优化请联系: BilibiliDownloader 类 (bilibili_downloader.py)
    ==========================================================================
    """
    from persona_engine.asr.bilibili_downloader import (
        BilibiliDownloader,
        VIDEO_SPLIT_MARKER,
    )
    from persona_engine.storage.persona_repo import TaskRepository

    task_repo_local = TaskRepository()
    downloader = BilibiliDownloader()
    audio_paths = []

    all_results = []  # 存储所有视频的ASR结果
    completed = 0
    failed = 0

    try:
        total = len(urls)

        # 先创建任务记录
        await task_repo_local.create(
            task_id=task_id,
            source_text=f"[ASR Task] Processing {total} videos: {', '.join(urls[:3])}{'...' if len(urls) > 3 else ''}",
            persona_ids=[],
            locked_terms=[],
        )

        # 更新任务状态
        await task_repo_local.update_result(
            task_id=task_id,
            best_text="",
            best_score=0.0,
            best_iteration=0,
            history_versions=[{
                "status": "processing",
                "total": total,
                "completed": 0,
                "failed": 0,
            }],
            status="running",
        )

        # 逐个处理视频
        for i, url in enumerate(urls):
            try:
                # 更新当前进度
                await task_repo_local.update_result(
                    task_id=task_id,
                    best_text="",
                    best_score=0.0,
                    best_iteration=0,
                    history_versions=[{
                        "status": f"processing ({i+1}/{total})",
                        "url": url,
                        "phase": "downloading",
                        "progress": (i / total) * 100,
                    }],
                    status="running",
                )

                # 下载视频并提取音频
                def progress_callback(progress: float, status: str):
                    logger.info(f"Task {task_id} [{i+1}/{total}]: {status}")

                # 下载并发控制
                await concurrency.acquire_download(url)
                try:
                    audio_path = await downloader.download_and_extract_audio(url, progress_callback)
                finally:
                    concurrency.release_download(url)
                audio_paths.append(audio_path)

                # 更新为转写中
                await task_repo_local.update_result(
                    task_id=task_id,
                    best_text="",
                    best_score=0.0,
                    best_iteration=0,
                    history_versions=[{
                        "status": f"processing ({i+1}/{total})",
                        "url": url,
                        "phase": "transcribing",
                        "progress": (i / total) * 100 + 50 / total,
                    }],
                    status="running",
                )

                # 执行ASR转写（WhisperWorker 常驻进程池，支持取消）
                asr_result = await _transcriber.transcribe_async(audio_path, task_id)

                # 返回 None 说明转写被取消
                if asr_result is None:
                    logger.info(f"Task {task_id} [{i+1}/{total}]: 转写被取消，停止处理")
                    break

                # 保存单个视频结果（带视频索引标识）
                video_result = {
                    "index": i,
                    "url": url,
                    "text": asr_result.text,
                    "wpm": asr_result.wpm,
                    "duration": asr_result.total_duration,
                    "word_count": len(asr_result.words),
                }
                all_results.append(video_result)

                # 立即保存中间结果（断点续传）
                await task_repo_local.update_result(
                    task_id=task_id,
                    best_text="",
                    best_score=0.0,
                    best_iteration=0,
                    history_versions=[{
                        "status": f"processing ({i+1}/{total})",
                        "url": url,
                        "phase": "completed",
                        "progress": ((i + 1) / total) * 100,
                    }],
                    status="running",
                    intermediate_results=all_results.copy(),
                )

                completed += 1
                logger.info(f"Task {task_id} [{i+1}/{total}] completed: {len(asr_result.text)} chars")

            except Exception as e:
                failed += 1
                logger.error(f"Task {task_id} [{i+1}/{total}] failed: {e}")
                all_results.append({
                    "index": i,
                    "url": url,
                    "error": str(e),
                })

        # 构建最终结果文本，使用分割标记区分不同视频
        final_texts = []
        for result in all_results:
            if "text" in result:
                final_texts.append(result["text"])

        # 用特殊标记连接多个视频的ASR结果
        combined_text = VIDEO_SPLIT_MARKER.join(final_texts)

        await task_repo_local.update_result(
            task_id=task_id,
            best_text=combined_text,
            best_score=0.0,
            best_iteration=0,
            history_versions=[{
                "status": "completed",
                "total": total,
                "completed": completed,
                "failed": failed,
                "results": [
                    {"index": r.get("index"), "url": r.get("url"), "text_len": len(r.get("text", ""))}
                    for r in all_results
                ],
            }],
            status="completed",
        )

        logger.info(f"Task {task_id} batch completed: {completed}/{total} successful")

    except Exception as e:
        logger.error(f"Task {task_id} batch failed: {e}")
        await task_repo_local.update_result(
            task_id=task_id,
            best_text="",
            best_score=0.0,
            best_iteration=0,
            history_versions=[{"status": "failed", "error": str(e)}],
            status="failed",
        )
    finally:
        # 释放任务槽位（在 routes_asr.py 中 acquire）
        concurrency.release_task(task_id)
        # 清理临时文件
        for audio_path in audio_paths:
            try:
                downloader.cleanup(audio_path)
            except Exception:
                pass


# ==================== 人格创建任务 ====================

async def _run_persona_from_videos_task_with_tracking(
    task_id: str,
    persona_id: str,
    video_urls: list[str],
):
    """
    后台任务包装器：追踪任务执行并在完成后自动取消注册

    Args:
        task_id: 任务ID
        persona_id: 人格ID
        video_urls: 视频链接列表
    """
    # 获取任务槽位（排队等待，最多 60 秒）
    acquired = await concurrency.acquire_task_wait(task_id, timeout=60.0)
    if not acquired:
        logger.error(f"Task {task_id}: 获取任务槽位超时，任务取消")
        await video_task_repo.update_status(task_id, "failed", error_message="并发任务已满，等待超时")
        task_registry.unregister(task_id)
        return

    try:
        await run_persona_from_videos_task(
            task_id=task_id,
            persona_id=persona_id,
            video_urls=video_urls,
        )
    except Exception as e:
        logger.error(f"Task {task_id} failed with exception: {e}", exc_info=True)
    finally:
        # 释放任务槽位
        concurrency.release_task(task_id)
        # 确保任务从注册表中移除
        task_registry.unregister(task_id)


async def _update_persona_progress(
    task_id: str,
    persona_id: str,
    completed: int,
    total: int,
    current_index: int | None = None,
    current_phase: str = "downloading",
    current_progress: float = 0.0,
    current_bv_id: str = None,
    failed: int = 0,
    completed_urls: list[str] | None = None,
    failed_urls: list[str] | None = None,
    asr_texts: list[str] | None = None,
):
    """
    更新人格进度到数据库（同时更新 personas.raw_json 和 VideoProcessingTask）

    Args:
        task_id: 视频任务ID
        persona_id: 人格ID
        completed: 已完成视频数
        total: 视频总数
        current_index: 当前处理的视频索引（从0开始）
        current_phase: 当前阶段 (downloading/transcribing)
        current_progress: 当前视频的进度百分比
        current_bv_id: 当前处理的视频BV号
        failed: 失败的视频数
        completed_urls: 已完成的URL列表
        asr_texts: 已提取的ASR文本列表
    """
    try:
        # 更新 VideoProcessingTask 进度（用于断点续传）
        await video_task_repo.update_progress(
            task_id=task_id,
            current_index=current_index if current_index is not None else completed,
            completed_urls=completed_urls,
            failed_urls=failed_urls,
            asr_texts=asr_texts,
        )

        # 同时更新 personas.raw_json（保持与现有 UI 的兼容性）
        raw_json = {
            "status": "processing",
            "task_id": task_id,
            "progress": f"{completed}/{total}",
            "completed_videos": completed,
            "total_videos": total,
            "failed_videos": failed,
        }

        # 添加当前视频详细信息
        if current_index is not None:
            raw_json["current_video"] = {
                "index": current_index,
                "phase": current_phase,
                "progress": current_progress,
                "bv_id": current_bv_id,
            }

        await persona_repo.update(persona_id, {"raw_json": raw_json})
    except Exception as e:
        logger.warning(f"Failed to update persona progress: {e}")


async def run_persona_from_videos_task(
    task_id: str,
    persona_id: str,
    video_urls: list[str],
):
    """
    后台任务：从视频创建新人格（带检查点机制和子进程强杀）

    ==========================================================================
    B站下载入口 #3 - 创建人格后台任务
    ==========================================================================
    调用链: create_persona() -> run_persona_from_videos_task() -> BilibiliDownloader
    支持入口: video_urls (直接链接) 和 space_url (通过 BilibiliSpaceDownloader 转换)
    反爬风险: 高（30个视频批量处理，极易触发412）

    进度追踪: 通过 _update_persona_progress() 实时更新到 personas.raw_json
    统一优化请联系: BilibiliDownloader 类 (bilibili_downloader.py)
    ==========================================================================
    """
    downloader = BilibiliDownloader()
    audio_paths = []
    all_results = []
    completed = 0
    failed = 0

    # 更新 VideoTask 状态为 processing
    await video_task_repo.update_status(task_id, "processing")

    def extract_bv_from_url(url: str) -> str:
        """从URL提取BV号"""
        match = regex_module.search(r'BV[\w]+', url)
        return match.group(0) if match else url

    def create_progress_callback(task_id: str, persona_id: str, total: int, i: int, bv_id: str):
        """创建进度回调函数"""
        last_update_time = [0]  # 用于限制更新频率

        def progress_callback(progress: float, status: str):
            # 每2秒更新一次进度，避免过于频繁的数据库写入
            current_time = asyncio.get_event_loop().time()
            if current_time - last_update_time[0] < 2.0:
                return
            last_update_time[0] = current_time

            asyncio.create_task(_update_persona_progress(
                task_id=task_id,
                persona_id=persona_id,
                completed=completed,
                total=total,
                current_index=i,
                current_phase="downloading",
                current_progress=progress,
                current_bv_id=bv_id,
                failed=failed,
            ))
        return progress_callback

    try:
        total = len(video_urls)
        logger.info(f"Task {task_id}: Starting persona creation from {total} videos")

        # 基础超时配置（兜底）
        BASE_DL_TIMEOUT = 180  # 3分钟
        BASE_ASR_TIMEOUT = 60  # 1分钟

        for i, url in enumerate(video_urls):
            bv_id = extract_bv_from_url(url)

            # 【检查点 1】：下载前状态检查（同步读取内存标志，无 DB 查询）
            if task_registry.is_cancelled(task_id):
                logger.info(f"[Task {task_id}] 检测到取消信号，停止下载 {url}")
                break

            # ==========================================
            # 步骤 0：获取视频时长，用于动态计算超时
            # ==========================================
            try:
                video_info = await downloader.get_video_info(url)
                duration_sec = video_info.get("duration", 0)
                if duration_sec <= 0:
                    duration_sec = 600  # 默认 10 分钟
                logger.info(f"[Task {task_id}] 视频 {bv_id} 时长: {duration_sec} 秒")
            except Exception as e:
                logger.warning(f"[Task {task_id}] 获取视频 {bv_id} 信息失败: {e}，使用默认时长 600 秒")
                duration_sec = 600

            # 动态超时计算
            # 下载超时：基础 3 分钟 + 视频时长 * 0.2（网络情况不好时留足余量）
            dl_timeout = BASE_DL_TIMEOUT + (duration_sec * 0.2)
            # 转写超时：基础 1 分钟 + 视频时长 * 2.5（保护本地显卡/CPU不被无限占用）
            asr_timeout = BASE_ASR_TIMEOUT + (duration_sec * 2.5)

            try:
                logger.info(f"Task {task_id} [{i+1}/{total}]: Downloading {url} (动态超时: {dl_timeout:.0f}秒)")

                # 更新进度为开始下载
                await _update_persona_progress(
                    task_id=task_id,
                    persona_id=persona_id,
                    completed=completed,
                    total=total,
                    current_index=i,
                    current_phase="downloading",
                    current_progress=0.0,
                    current_bv_id=bv_id,
                    failed=failed,
                )

                # 创建进度回调
                progress_cb = create_progress_callback(task_id, persona_id, total, i, bv_id)

                # 【步骤 1】：动态超时下载（带下载并发控制）
                await concurrency.acquire_download(url)
                try:
                    audio_path = await asyncio.wait_for(
                        downloader.download_and_extract_audio(url, progress_callback=progress_cb),
                        timeout=dl_timeout,
                    )
                finally:
                    concurrency.release_download(url)
                audio_paths.append(audio_path)

                # 【检查点 2】：转写前状态检查与垃圾清理（同步读取内存标志）
                if task_registry.is_cancelled(task_id):
                    logger.info(f"[Task {task_id}] 检测到取消信号，放弃转写并清理: {audio_path}")
                    if os.path.exists(audio_path):
                        os.remove(audio_path)
                    break

                # 更新进度为转写阶段
                await _update_persona_progress(
                    task_id=task_id,
                    persona_id=persona_id,
                    completed=completed,
                    total=total,
                    current_index=i,
                    current_phase="transcribing",
                    current_progress=50.0,
                    current_bv_id=bv_id,
                    failed=failed,
                )

                # 【步骤 2】：动态超时转写（WhisperWorker 常驻进程池，支持取消信号）
                logger.info(f"Task {task_id} [{i+1}/{total}]: 开始转写 (动态超时: {asr_timeout:.0f}秒)")
                _asr = await asyncio.wait_for(
                    _transcriber.transcribe_async(audio_path, task_id),
                    timeout=asr_timeout,
                )
                asr_text = _asr.text if _asr else None

                # 返回 None 说明转写被中途中断（用户取消）
                if asr_text is None:
                    logger.info(f"[Task {task_id}] 转写被强制中断，清理文件: {audio_path}")
                    if os.path.exists(audio_path):
                        os.remove(audio_path)
                    break

                # 检查是否为空文本
                if not asr_text or len(asr_text.strip()) == 0:
                    logger.warning(f"[Task {task_id}] 转写结果为空，跳过: {url}")
                    failed += 1
                    if os.path.exists(audio_path):
                        os.remove(audio_path)
                    await _update_persona_progress(
                        task_id=task_id,
                        persona_id=persona_id,
                        completed=completed,
                        total=total,
                        current_index=i,
                        current_phase="failed",
                        current_progress=0.0,
                        current_bv_id=bv_id,
                        failed=failed,
                        failed_urls=[url],
                    )
                    continue

                all_results.append({
                    "index": i,
                    "url": url,
                    "bv_id": bv_id,
                    "text": asr_text,
                })
                completed += 1
                logger.info(f"Task {task_id} [{i+1}/{total}]: Transcribed {len(asr_text)} chars")

                # 每完成1个视频即更新进度
                await _update_persona_progress(
                    task_id=task_id,
                    persona_id=persona_id,
                    completed=completed,
                    total=total,
                    current_index=i,
                    current_phase="completed",
                    current_progress=100.0,
                    current_bv_id=bv_id,
                    failed=failed,
                    completed_urls=[url],
                    asr_texts=[asr_text],
                )

                # 正常完成清理临时音频
                if os.path.exists(audio_path):
                    os.remove(audio_path)

            except asyncio.TimeoutError:
                failed += 1
                timeout_type = "下载" if not audio_paths or url not in str(audio_paths) else "转写"
                logger.error(f"[Task {task_id}] [{i+1}/{total}] {timeout_type}超时 ({dl_timeout:.0f}s 或 {asr_timeout:.0f}s)！跳过视频: {url}")
                all_results.append({
                    "index": i,
                    "url": url,
                    "bv_id": bv_id,
                    "error": f"Timeout ({timeout_type}) after {dl_timeout:.0f}s/{asr_timeout:.0f}s",
                })
                # 确保临时文件被清理
                if 'audio_path' in locals() and os.path.exists(audio_path):
                    os.remove(audio_path)
                # 更新失败进度
                await _update_persona_progress(
                    task_id=task_id,
                    persona_id=persona_id,
                    completed=completed,
                    total=total,
                    current_index=i,
                    current_phase="failed",
                    current_progress=0.0,
                    current_bv_id=bv_id,
                    failed=failed,
                    failed_urls=[url],
                )
            except Exception as e:
                failed += 1
                logger.error(f"Task {task_id} [{i+1}/{total}] failed: {e}")
                all_results.append({
                    "index": i,
                    "url": url,
                    "bv_id": bv_id,
                    "error": str(e),
                })
                # 确保临时文件被清理
                if 'audio_path' in locals() and os.path.exists(audio_path):
                    os.remove(audio_path)
                # 更新失败进度
                await _update_persona_progress(
                    task_id=task_id,
                    persona_id=persona_id,
                    completed=completed,
                    total=total,
                    current_index=i,
                    current_phase="failed",
                    current_progress=0.0,
                    current_bv_id=bv_id,
                    failed=failed,
                    failed_urls=[url],
                )

        # 构建ASR文本
        final_texts = [r["text"] for r in all_results if "text" in r]
        combined_text = VIDEO_SPLIT_MARKER.join(final_texts)

        if not final_texts:
            logger.error(f"Task {task_id}: No successful transcriptions")
            return

        # 使用人格提取器生成画像
        extractor = PersonalityExtractor()
        # 获取原有人格的名称（用于保持名称不变）
        existing_persona = await persona_repo.get_by_id(persona_id)
        original_name = existing_persona.name if existing_persona else None
        profile = await extractor.extract(
            texts=final_texts,
            author_name=original_name,  # 保持原有名称
        )

        # 构建更新字典（与数据库字段对应）
        updates = {
            "name": profile.name,
            "verbal_tics": profile.verbal_tics,
            "grammar_prefs": profile.grammar_prefs,
            "logic_architecture": {
                "opening_style": profile.logic_architecture.opening_style,
                "transition_patterns": profile.logic_architecture.transition_patterns,
                "closing_style": profile.logic_architecture.closing_style,
                "topic_organization": profile.logic_architecture.topic_organization,
            },
            "temporal_patterns": {
                "avg_pause_duration": profile.temporal_patterns.avg_pause_duration,
                "pause_frequency": profile.temporal_patterns.pause_frequency,
                "speech_rhythm": profile.temporal_patterns.speech_rhythm,
                "excitement_curve": profile.temporal_patterns.excitement_curve,
            },
            "raw_json": {
                "status": "completed",
                "task_id": task_id,
                "source_video_count": total,
                "successful_count": completed,
                "failed_count": failed,
            },
            "source_asr_texts": final_texts,
        }

        await persona_repo.update(persona_id, updates)
        # 更新 VideoTask 状态为 completed
        await video_task_repo.update_status(task_id, "completed")
        logger.info(f"Task {task_id}: Persona {persona_id} created successfully")

    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}")
        # 更新 VideoTask 状态为 failed
        await video_task_repo.update_status(task_id, "failed", error_message=str(e))
    finally:
        # 清理临时文件
        for audio_path in audio_paths:
            try:
                downloader.cleanup(audio_path)
            except Exception:
                pass


# ==================== 人格升级任务 ====================

async def _run_persona_upgrade_task_with_tracking(
    task_id: str,
    persona_id: str,
    video_urls: list[str],
):
    """
    后台任务包装器：追踪任务执行并在完成后自动取消注册

    Args:
        task_id: 任务ID
        persona_id: 人格ID
        video_urls: 视频链接列表
    """
    # 获取任务槽位（排队等待，最多 60 秒）
    acquired = await concurrency.acquire_task_wait(task_id, timeout=60.0)
    if not acquired:
        logger.error(f"Task {task_id}: 获取任务槽位超时，任务取消")
        task_registry.unregister(task_id)
        return

    try:
        await run_persona_upgrade_task(
            task_id=task_id,
            persona_id=persona_id,
            video_urls=video_urls,
        )
    except Exception as e:
        logger.error(f"Task {task_id} failed with exception: {e}", exc_info=True)
    finally:
        # 释放任务槽位
        concurrency.release_task(task_id)
        # 确保任务从注册表中移除
        task_registry.unregister(task_id)


async def run_persona_upgrade_task(
    task_id: str,
    persona_id: str,
    video_urls: list[str],
):
    """
    后台任务：追加视频到已有人格并重新计算

    ==========================================================================
    B站下载入口 #4 - 追加视频后台任务
    ==========================================================================
    调用链: add_videos_to_persona() -> run_persona_upgrade_task() -> BilibiliDownloader
    反爬风险: 中等（批量请求，取决于追加视频数量）

    注意: 此函数目前缺少详细进度追踪（TODO: 统一进度追踪机制）
    统一优化请联系: BilibiliDownloader 类 (bilibili_downloader.py)
    ==========================================================================
    """
    downloader = BilibiliDownloader()
    audio_paths = []
    all_results = []
    completed = 0
    failed = 0

    try:
        total = len(video_urls)
        logger.info(f"Task {task_id}: Starting persona upgrade for {persona_id} with {total} videos")

        # 获取现有的人格数据
        existing_persona = await persona_repo.get_by_id(persona_id)
        if not existing_persona:
            logger.error(f"Task {task_id}: Persona {persona_id} not found")
            return

        existing_texts = existing_persona.source_asr_texts or []
        logger.info(f"Task {task_id}: Existing texts: {len(existing_texts)} videos")

        # 逐个处理新视频
        for i, url in enumerate(video_urls):
            try:
                logger.info(f"Task {task_id} [{i+1}/{total}]: Downloading {url}")

                # 下载视频并提取音频（带下载并发控制）
                await concurrency.acquire_download(url)
                try:
                    audio_path = await downloader.download_and_extract_audio(url)
                finally:
                    concurrency.release_download(url)
                audio_paths.append(audio_path)

                # 执行ASR转写（WhisperWorker 常驻进程池，支持取消）
                asr_result = await _transcriber.transcribe_async(audio_path, task_id)

                if asr_result is None:
                    logger.info(f"Task {task_id} [{i+1}/{total}]: 转写被取消，停止处理")
                    break

                all_results.append({
                    "index": i,
                    "url": url,
                    "text": asr_result.text,
                })
                completed += 1
                logger.info(f"Task {task_id} [{i+1}/{total}]: Transcribed {len(asr_result.text)} chars")

            except Exception as e:
                failed += 1
                logger.error(f"Task {task_id} [{i+1}/{total}] failed: {e}")
                all_results.append({
                    "index": i,
                    "url": url,
                    "error": str(e),
                })

        # 追加新的ASR文本
        new_texts = [r["text"] for r in all_results if "text" in r]
        all_texts = existing_texts + new_texts

        if not new_texts:
            logger.error(f"Task {task_id}: No successful new transcriptions")
            return

        # 重新计算人格画像
        extractor = PersonalityExtractor()
        profile = await extractor.extract(
            texts=all_texts,
            author_name=existing_persona.name,
        )

        # 构建更新字典（与数据库字段对应）
        updates = {
            "name": profile.name,
            "verbal_tics": profile.verbal_tics,
            "grammar_prefs": profile.grammar_prefs,
            "logic_architecture": {
                "opening_style": profile.logic_architecture.opening_style,
                "transition_patterns": profile.logic_architecture.transition_patterns,
                "closing_style": profile.logic_architecture.closing_style,
                "topic_organization": profile.logic_architecture.topic_organization,
            },
            "temporal_patterns": {
                "avg_pause_duration": profile.temporal_patterns.avg_pause_duration,
                "pause_frequency": profile.temporal_patterns.pause_frequency,
                "speech_rhythm": profile.temporal_patterns.speech_rhythm,
                "excitement_curve": profile.temporal_patterns.excitement_curve,
            },
            "raw_json": {
                "status": "upgraded",
                "task_id": task_id,
                "previous_video_count": len(existing_texts),
                "new_video_count": total,
                "successful_new_count": completed,
                "failed_new_count": failed,
            },
            "source_asr_texts": all_texts,
        }

        await persona_repo.update(persona_id, updates)
        logger.info(f"Task {task_id}: Persona {persona_id} upgraded successfully with {len(all_texts)} total videos")

    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}")
    finally:
        # 清理临时文件
        for audio_path in audio_paths:
            try:
                downloader.cleanup(audio_path)
            except Exception:
                pass

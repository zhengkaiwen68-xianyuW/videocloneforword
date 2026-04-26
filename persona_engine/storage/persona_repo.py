"""
人格仓储模块

提供人格画像的 CRUD 操作
"""

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update, delete, desc, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exceptions import PersonaNotFoundError, DatabaseError, StorageError
from ..core.types import (
    ContentStructureMap,
    DeepPsychology,
    HookAnalysis,
    HookType,
    LogicArchitecture,
    PersonalityProfile,
    TemporalPattern,
    TopicTechnique,
)
from .database import (
    ContentStructureModel,
    HookAnalysisModel,
    PersonaModel,
    TopicTechniqueModel,
    VideoProcessingTaskModel,
    database,
)


logger = logging.getLogger(__name__)


class PersonaRepository:
    """
    人格仓储

    提供人格画像的创建、读取、更新、删除操作
    """

    def __init__(self):
        self.db = database

    async def create(self, profile: PersonalityProfile) -> PersonalityProfile:
        """
        创建新人格画像

        Args:
            profile: 人格画像

        Returns:
            创建后的人格画像

        Raises:
            DatabaseError: 创建失败
        """
        try:
            async with self.db.session() as session:
                model = PersonaModel(
                    id=profile.id,
                    name=profile.name,
                    verbal_tics=profile.verbal_tics,
                    grammar_prefs=profile.grammar_prefs,
                    logic_architecture={
                        "opening_style": profile.logic_architecture.opening_style,
                        "transition_patterns": profile.logic_architecture.transition_patterns,
                        "closing_style": profile.logic_architecture.closing_style,
                        "topic_organization": profile.logic_architecture.topic_organization,
                    },
                    temporal_patterns={
                        "avg_pause_duration": profile.temporal_patterns.avg_pause_duration,
                        "pause_frequency": profile.temporal_patterns.pause_frequency,
                        "speech_rhythm": profile.temporal_patterns.speech_rhythm,
                        "excitement_curve": profile.temporal_patterns.excitement_curve,
                    },
                    raw_json=profile.raw_json,
                    source_asr_texts=profile.source_asr_texts,
                    topic_techniques=profile.topic_techniques.to_dict() if profile.topic_techniques else None,
                    hook_techniques=[h.to_dict() for h in profile.hook_techniques],
                    structure_patterns=[s.to_dict() for s in profile.structure_patterns],
                    created_at=profile.created_at,
                    updated_at=profile.updated_at,
                )
                session.add(model)
                await session.commit()
                await session.refresh(model)

            logger.info(f"Persona created: {profile.id} ({profile.name})")
            return profile

        except Exception as e:
            raise DatabaseError(
                message=f"Failed to create persona: {str(e)}",
                operation="create",
                details={"persona_id": profile.id},
            )

    async def get_by_id(self, persona_id: str) -> PersonalityProfile:
        """
        根据 ID 获取人格画像

        Args:
            persona_id: 人格 ID

        Returns:
            人格画像

        Raises:
            PersonaNotFoundError: 不存在
        """
        try:
            async with self.db.session() as session:
                result = await session.execute(
                    select(PersonaModel).where(PersonaModel.id == persona_id)
                )
                model = result.scalar_one_or_none()

            if model is None:
                raise PersonaNotFoundError(persona_id)

            return self._model_to_profile(model)

        except PersonaNotFoundError:
            raise
        except Exception as e:
            raise DatabaseError(
                message=f"Failed to get persona: {str(e)}",
                operation="get_by_id",
                details={"persona_id": persona_id},
            )

    async def get_all(self) -> list[PersonalityProfile]:
        """
        获取所有人格画像

        Returns:
            人格画像列表
        """
        try:
            async with self.db.session() as session:
                result = await session.execute(
                    select(PersonaModel).order_by(PersonaModel.created_at.desc())
                )
                models = result.scalars().all()

            return [self._model_to_profile(m) for m in models]

        except Exception as e:
            raise DatabaseError(
                message=f"Failed to get all personas: {str(e)}",
                operation="get_all",
            )

    async def update(
        self,
        persona_id: str,
        updates: dict[str, Any],
    ) -> PersonalityProfile:
        """
        更新人格画像

        Args:
            persona_id: 人格 ID
            updates: 更新字段字典

        Returns:
            更新后的人格画像

        Raises:
            PersonaNotFoundError: 不存在
        """
        try:
            # 先检查是否存在
            await self.get_by_id(persona_id)

            updates["updated_at"] = datetime.now()

            async with self.db.session() as session:
                await session.execute(
                    update(PersonaModel)
                    .where(PersonaModel.id == persona_id)
                    .values(**updates)
                )
                await session.commit()

            return await self.get_by_id(persona_id)

        except PersonaNotFoundError:
            raise
        except Exception as e:
            raise DatabaseError(
                message=f"Failed to update persona: {str(e)}",
                operation="update",
                details={"persona_id": persona_id, "updates": updates},
            )

    async def delete(self, persona_id: str) -> bool:
        """
        删除人格画像

        Args:
            persona_id: 人格 ID

        Returns:
            是否删除成功

        Raises:
            PersonaNotFoundError: 不存在
        """
        try:
            # 先检查是否存在
            await self.get_by_id(persona_id)

            async with self.db.session() as session:
                await session.execute(
                    delete(PersonaModel).where(PersonaModel.id == persona_id)
                )
                await session.commit()

            logger.info(f"Persona deleted: {persona_id}")
            return True

        except PersonaNotFoundError:
            raise
        except Exception as e:
            raise DatabaseError(
                message=f"Failed to delete persona: {str(e)}",
                operation="delete",
                details={"persona_id": persona_id},
            )

    async def exists(self, persona_id: str) -> bool:
        """
        检查人格是否存在

        Args:
            persona_id: 人格 ID

        Returns:
            是否存在
        """
        try:
            async with self.db.session() as session:
                result = await session.execute(
                    select(PersonaModel.id).where(PersonaModel.id == persona_id)
                )
                return result.scalar_one_or_none() is not None
        except Exception:
            return False

    async def count(self) -> int:
        """
        获取人格总数

        Returns:
            人格数量
        """
        try:
            async with self.db.session() as session:
                result = await session.execute(
                    select(func.count()).select_from(PersonaModel)
                )
                return result.scalar() or 0
        except Exception as e:
            raise DatabaseError(
                message=f"Failed to count personas: {str(e)}",
                operation="count",
            )

    async def get_by_ids(self, persona_ids: list[str]) -> list[PersonalityProfile]:
        """
        根据 ID 列表批量获取人格

        Args:
            persona_ids: ID 列表

        Returns:
            人格画像列表
        """
        try:
            async with self.db.session() as session:
                result = await session.execute(
                    select(PersonaModel).where(PersonaModel.id.in_(persona_ids))
                )
                models = result.scalars().all()

            return [self._model_to_profile(m) for m in models]

        except Exception as e:
            raise DatabaseError(
                message=f"Failed to get personas by ids: {str(e)}",
                operation="get_by_ids",
                details={"persona_ids": persona_ids},
            )

    async def mark_stale_processing_as_failed(self, threshold: timedelta) -> int:
        """
        清理卡死的后台任务（服务器异常关闭遗留）

        将状态为 processing 但创建时间超过阈值的 persona 标记为 failed

        Args:
            threshold: 时间阈值

        Returns:
            清理的任务数量
        """
        try:
            from datetime import datetime as dt
            cutoff_time = dt.now() - threshold

            async with self.db.session() as session:
                # 使用 SQL JSON 提取直接在数据库层面过滤，避免加载所有数据到内存
                # SQLite 的 json_extract 提取 raw_json.status 字段
                result = await session.execute(
                    select(PersonaModel).where(
                        PersonaModel.created_at < cutoff_time,
                        func.json_extract(PersonaModel.raw_json, '$.status') == 'processing'
                    )
                )
                stale_models = result.scalars().all()

                if not stale_models:
                    return 0

                # 批量更新为 failed
                for model in stale_models:
                    model.raw_json = dict(model.raw_json or {})
                    model.raw_json["status"] = "failed"
                    model.raw_json["error"] = f"Stale task cleaned up on startup (created {model.created_at})"
                    model.updated_at = dt.now()

                await session.commit()
                logger.warning(f"Marked {len(stale_models)} stale processing tasks as failed")

            return len(stale_models)

        except Exception as e:
            logger.error(f"Failed to mark stale processing tasks: {e}")
            return 0

    def _model_to_profile(self, model: PersonaModel) -> PersonalityProfile:
        """
        将数据库模型转换为 PersonalityProfile

        Args:
            model: 数据库模型

        Returns:
            人格画像
        """
        logic_arch_data = model.logic_architecture or {}
        temporal_data = model.temporal_patterns or {}
        raw_json_data = model.raw_json or {}

        # 从 raw_json 还原 deep_psychology（存储时保存在 raw_json.deep_psychology）
        deep_psy_data = raw_json_data.get("deep_psychology", {})
        deep_psychology = DeepPsychology(
            emotional_tone=deep_psy_data.get("emotional_tone", "平稳中立"),
            emotional_arc=deep_psy_data.get("emotional_arc", ["引入", "展开", "收尾"]),
            rhetorical_devices=deep_psy_data.get("rhetorical_devices", []),
            lexicon=deep_psy_data.get("lexicon", []),
        )

        # 还原技法数据
        topic_tech_data = model.topic_techniques
        topic_techniques = TopicTechnique.from_dict(topic_tech_data) if topic_tech_data else None

        hook_techniques = [
            HookAnalysis.from_dict(h) for h in (model.hook_techniques or [])
        ]

        structure_patterns = [
            ContentStructureMap.from_dict(s) for s in (model.structure_patterns or [])
        ]

        return PersonalityProfile(
            id=model.id,
            name=model.name,
            verbal_tics=model.verbal_tics or [],
            grammar_prefs=model.grammar_prefs or [],
            logic_architecture=LogicArchitecture(
                opening_style=logic_arch_data.get("opening_style", ""),
                transition_patterns=logic_arch_data.get("transition_patterns", []),
                closing_style=logic_arch_data.get("closing_style", ""),
                topic_organization=logic_arch_data.get("topic_organization", ""),
            ),
            temporal_patterns=TemporalPattern(
                avg_pause_duration=temporal_data.get("avg_pause_duration", 0.5),
                pause_frequency=temporal_data.get("pause_frequency", 1.0),
                speech_rhythm=temporal_data.get("speech_rhythm", "medium"),
                excitement_curve=temporal_data.get("excitement_curve", []),
            ),
            deep_psychology=deep_psychology,
            topic_techniques=topic_techniques,
            hook_techniques=hook_techniques,
            structure_patterns=structure_patterns,
            raw_json=raw_json_data,
            source_asr_texts=model.source_asr_texts or [],
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class TaskRepository:
    """
    任务仓储

    提供重写任务的 CRUD 操作
    """

    def __init__(self):
        self.db = database

    async def create(
        self,
        task_id: str,
        source_text: str,
        persona_ids: list[str],
        locked_terms: list[str],
    ) -> dict:
        """创建任务记录"""
        try:
            async with self.db.session() as session:
                from .database import RewriteTaskModel

                model = RewriteTaskModel(
                    id=task_id,
                    source_text=source_text,
                    persona_ids=persona_ids,
                    locked_terms=locked_terms,
                    status="pending",
                    best_text="",
                    best_score=0.0,
                    best_iteration=0,
                    history_versions=[],
                )
                session.add(model)
                await session.commit()

            return {"task_id": task_id, "status": "pending"}

        except Exception as e:
            raise DatabaseError(
                message=f"Failed to create task: {str(e)}",
                operation="create",
                details={"task_id": task_id},
            )

    async def get_status(self, task_id: str) -> dict:
        """获取任务状态"""
        try:
            async with self.db.session() as session:
                from .database import RewriteTaskModel

                result = await session.execute(
                    select(RewriteTaskModel).where(RewriteTaskModel.id == task_id)
                )
                model = result.scalar_one_or_none()

            if model is None:
                from ..core.exceptions import TaskNotFoundError
                raise TaskNotFoundError(task_id)

            return {
                "task_id": model.id,
                "status": model.status,
                "best_score": model.best_score,
                "best_text": model.best_text,
                "best_iteration": model.best_iteration,
                "history_count": len(model.history_versions or []),
                "error_message": model.error_message,
                "created_at": model.created_at.isoformat(),
                "completed_at": model.completed_at.isoformat() if model.completed_at else None,
            }

        except Exception as e:
            if isinstance(e, TaskNotFoundError):
                raise
            raise DatabaseError(
                message=f"Failed to get task status: {str(e)}",
                operation="get_status",
                details={"task_id": task_id},
            )

    async def mark_running_as_interrupted(self) -> int:
        """
        将所有 running 状态的任务标记为 interrupted

        服务重启时调用，用于检测中断的任务

        Returns:
            被标记的任务数量
        """
        try:
            async with self.db.session() as session:
                from .database import RewriteTaskModel

                result = await session.execute(
                    update(RewriteTaskModel)
                    .where(RewriteTaskModel.status == "running")
                    .values(status="interrupted")
                )
                await session.commit()
                count = result.rowcount

            if count > 0:
                logger.info(f"Marked {count} running tasks as interrupted")
            return count

        except Exception as e:
            logger.error(f"Failed to mark running tasks as interrupted: {e}")
            return 0

    async def get_interrupted_tasks(self) -> list[dict]:
        """
        获取所有中断的任务

        Returns:
            中断任务列表
        """
        try:
            async with self.db.session() as session:
                from .database import RewriteTaskModel

                result = await session.execute(
                    select(RewriteTaskModel).where(
                        RewriteTaskModel.status == "interrupted"
                    )
                )
                models = result.scalars().all()

            return [
                {
                    "task_id": m.id,
                    "source_text": m.source_text[:100] + "..." if len(m.source_text) > 100 else m.source_text,
                    "status": m.status,
                    "intermediate_results_count": len(m.intermediate_results or []),
                    "history_versions": m.history_versions,
                    "created_at": m.created_at.isoformat(),
                }
                for m in models
            ]

        except Exception as e:
            raise DatabaseError(
                message=f"Failed to get interrupted tasks: {str(e)}",
                operation="get_interrupted_tasks",
            )

    async def update_result(
        self,
        task_id: str,
        best_text: str,
        best_score: float,
        best_iteration: int,
        history_versions: list,
        status: str = "running",
        intermediate_results: list | None = None,
    ) -> bool:
        """更新任务结果"""
        try:
            async with self.db.session() as session:
                from .database import RewriteTaskModel

                update_values = {
                    "best_text": best_text,
                    "best_score": best_score,
                    "best_iteration": best_iteration,
                    "history_versions": history_versions,
                    "status": status,
                }
                if intermediate_results is not None:
                    update_values["intermediate_results"] = intermediate_results

                await session.execute(
                    update(RewriteTaskModel)
                    .where(RewriteTaskModel.id == task_id)
                    .values(**update_values)
                )
                await session.commit()

            return True

        except Exception as e:
            raise DatabaseError(
                message=f"Failed to update task result: {str(e)}",
                operation="update_result",
                details={"task_id": task_id},
            )

    async def complete(
        self,
        task_id: str,
        status: str = "completed",
        error_message: str | None = None,
    ) -> bool:
        """完成任务"""
        try:
            async with self.db.session() as session:
                from .database import RewriteTaskModel

                await session.execute(
                    update(RewriteTaskModel)
                    .where(RewriteTaskModel.id == task_id)
                    .values(
                        status=status,
                        error_message=error_message,
                        completed_at=datetime.now(),
                    )
                )
                await session.commit()

            return True

        except Exception as e:
            raise DatabaseError(
                message=f"Failed to complete task: {str(e)}",
                operation="complete",
                details={"task_id": task_id},
            )

    async def get_recent_completed_tasks(self, limit: int = 5) -> list[dict]:
        """
        获取最近完成的重写任务（用于前端恢复历史结果）

        Returns:
            最近完成的任务列表，按完成时间倒序
        """
        try:
            async with self.db.session() as session:
                from .database import RewriteTaskModel

                result = await session.execute(
                    select(RewriteTaskModel)
                    .where(
                        RewriteTaskModel.status.in_(
                            ["completed", "completed_below_threshold"]
                        )
                    )
                    .order_by(RewriteTaskModel.completed_at.desc())
                    .limit(limit)
                )
                models = result.scalars().all()

            return [
                {
                    "task_id": m.id,
                    "source_text": m.source_text[:100] + "..." if len(m.source_text) > 100 else m.source_text,
                    "status": m.status,
                    "best_score": m.best_score,
                    "best_text": m.best_text,
                    "best_iteration": m.best_iteration,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                    "completed_at": m.completed_at.isoformat() if m.completed_at else None,
                }
                for m in models
            ]

        except Exception as e:
            raise DatabaseError(
                message=f"Failed to get recent completed tasks: {str(e)}",
                operation="get_recent_completed_tasks",
            )


class VideoTaskRepository:
    """
    视频处理任务的存储库

    支持：
    - 任务创建与查询
    - 高频进度更新（局部更新，避免并发冲突）
    - 断点续传（查询 pending/processing 状态任务）
    """

    def __init__(self):
        self.db = database

    async def create(
        self,
        task_id: str,
        persona_id: str,
        video_urls: list[str],
    ) -> VideoProcessingTaskModel:
        """
        创建新的视频处理任务

        Args:
            task_id: 任务ID
            persona_id: 关联的人格ID
            video_urls: 视频链接列表

        Returns:
            创建的任务模型
        """
        try:
            async with self.db.session() as session:
                task = VideoProcessingTaskModel(
                    id=task_id,
                    persona_id=persona_id,
                    video_urls=video_urls,
                    status="pending",
                    completed_urls=[],
                    failed_urls=[],
                    asr_texts=[],
                )
                session.add(task)
                await session.flush()
                await session.refresh(task)
                return task

        except Exception as e:
            raise DatabaseError(
                message=f"Failed to create video task: {str(e)}",
                operation="create",
                details={"task_id": task_id, "persona_id": persona_id},
            )

    async def get(self, task_id: str) -> VideoProcessingTaskModel | None:
        """
        获取指定的视频处理任务详情

        Args:
            task_id: 任务ID

        Returns:
            任务模型或 None
        """
        try:
            async with self.db.session() as session:
                result = await session.execute(
                    select(VideoProcessingTaskModel)
                    .where(VideoProcessingTaskModel.id == task_id)
                )
                return result.scalar_one_or_none()

        except Exception as e:
            raise DatabaseError(
                message=f"Failed to get video task: {str(e)}",
                operation="get",
                details={"task_id": task_id},
            )

    async def update_progress(
        self,
        task_id: str,
        current_index: int,
        completed_urls: list[str] | None = None,
        failed_urls: list[str] | None = None,
        asr_texts: list[str] | None = None,
    ) -> bool:
        """
        增量更新任务进度（每完成一个视频或发生错误时调用）

        使用 update 语句进行局部更新，避免并发覆写。
        completed_urls / failed_urls / asr_texts 会与现有数据合并，而非替换。

        Args:
            task_id: 任务ID
            current_index: 当前处理到的视频索引
            completed_urls: 新增完成的URL列表（会合并）
            failed_urls: 新增失败的URL列表（会合并）
            asr_texts: 新增的ASR文本列表（会合并）

        Returns:
            是否更新成功
        """
        try:
            async with self.db.session() as session:
                # 先获取现有数据
                result = await session.execute(
                    select(VideoProcessingTaskModel)
                    .where(VideoProcessingTaskModel.id == task_id)
                )
                task = result.scalar_one_or_none()
                if not task:
                    return False

                # 增量合并
                update_data = {
                    "current_index": current_index,
                    "updated_at": datetime.now(),
                }

                if completed_urls is not None:
                    existing_completed = list(task.completed_urls or [])
                    update_data["completed_urls"] = existing_completed + completed_urls
                if failed_urls is not None:
                    existing_failed = list(task.failed_urls or [])
                    update_data["failed_urls"] = existing_failed + failed_urls
                if asr_texts is not None:
                    existing_asr = list(task.asr_texts or [])
                    update_data["asr_texts"] = existing_asr + asr_texts

                await session.execute(
                    update(VideoProcessingTaskModel)
                    .where(VideoProcessingTaskModel.id == task_id)
                    .values(**update_data)
                )
                await session.commit()
                return True

        except Exception as e:
            raise DatabaseError(
                message=f"Failed to update video task progress: {str(e)}",
                operation="update_progress",
                details={"task_id": task_id},
            )

    async def update_status(
        self,
        task_id: str,
        status: str,
        error_message: str | None = None,
    ) -> bool:
        """
        更新任务状态

        Args:
            task_id: 任务ID
            status: 新状态 (pending/processing/completed/failed/cancelled)
            error_message: 错误信息（可选）

        Returns:
            是否更新成功
        """
        try:
            async with self.db.session() as session:
                update_data = {
                    "status": status,
                    "updated_at": datetime.now(),
                }
                if error_message is not None:
                    update_data["error_message"] = error_message

                result = await session.execute(
                    update(VideoProcessingTaskModel)
                    .where(VideoProcessingTaskModel.id == task_id)
                    .values(**update_data)
                )
                await session.commit()
                return result.rowcount > 0

        except Exception as e:
            raise DatabaseError(
                message=f"Failed to update video task status: {str(e)}",
                operation="update_status",
                details={"task_id": task_id, "status": status},
            )

    async def list_tasks(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[VideoProcessingTaskModel]:
        """
        获取任务列表（分页，按创建时间倒序）

        Args:
            limit: 每页数量
            offset: 偏移量

        Returns:
            任务列表
        """
        try:
            async with self.db.session() as session:
                result = await session.execute(
                    select(VideoProcessingTaskModel)
                    .order_by(desc(VideoProcessingTaskModel.created_at))
                    .limit(limit)
                    .offset(offset)
                )
                return list(result.scalars().all())

        except Exception as e:
            raise DatabaseError(
                message=f"Failed to list video tasks: {str(e)}",
                operation="list_tasks",
            )

    async def get_unfinished_tasks(self) -> list[VideoProcessingTaskModel]:
        """
        获取所有未完成的任务（服务器重启时调用，用于断点续传）

        Returns:
            pending 或 processing 状态的任务列表
        """
        try:
            async with self.db.session() as session:
                result = await session.execute(
                    select(VideoProcessingTaskModel)
                    .where(VideoProcessingTaskModel.status.in_(["pending", "processing"]))
                    .order_by(VideoProcessingTaskModel.created_at)
                )
                return list(result.scalars().all())

        except Exception as e:
            raise DatabaseError(
                message=f"Failed to get unfinished tasks: {str(e)}",
                operation="get_unfinished_tasks",
            )

    async def get_by_persona(self, persona_id: str) -> list[VideoProcessingTaskModel]:
        """
        获取指定人格下的所有任务

        Args:
            persona_id: 人格ID

        Returns:
            任务列表
        """
        try:
            async with self.db.session() as session:
                result = await session.execute(
                    select(VideoProcessingTaskModel)
                    .where(VideoProcessingTaskModel.persona_id == persona_id)
                    .order_by(desc(VideoProcessingTaskModel.created_at))
                )
                return list(result.scalars().all())

        except Exception as e:
            raise DatabaseError(
                message=f"Failed to get tasks by persona: {str(e)}",
                operation="get_by_persona",
                details={"persona_id": persona_id},
            )


class TechniqueRepository:
    """
    技法仓储

    提供钩子分析、选题技法、内容结构映射的 CRUD 操作
    """

    def __init__(self):
        self.db = database

    # ── Hook Analysis ──

    async def save_hook(self, hook: HookAnalysis) -> str:
        """保存钩子分析记录"""
        hook_id = hook.id or str(uuid.uuid4())
        try:
            async with self.db.session() as session:
                model = HookAnalysisModel(
                    id=hook_id,
                    persona_id=hook.persona_id,
                    hook_text=hook.hook_text,
                    hook_type=hook.hook_type.value,
                    psychological_mechanism=hook.psychological_mechanism,
                    structural_formula=hook.structural_formula,
                    why_it_works=hook.why_it_works,
                    reconstruction_template=hook.reconstruction_template,
                    source_video_url=hook.source_video_url,
                    created_at=hook.created_at,
                )
                session.add(model)
                await session.commit()
            logger.info(f"Hook analysis saved: {hook_id}")
            return hook_id
        except Exception as e:
            raise DatabaseError(
                message=f"Failed to save hook analysis: {str(e)}",
                operation="save_hook",
            )

    async def get_hooks_by_persona(self, persona_id: str) -> list[HookAnalysis]:
        """获取指定人格的所有钩子分析"""
        try:
            async with self.db.session() as session:
                result = await session.execute(
                    select(HookAnalysisModel)
                    .where(HookAnalysisModel.persona_id == persona_id)
                    .order_by(desc(HookAnalysisModel.created_at))
                )
                models = result.scalars().all()
            return [self._model_to_hook(m) for m in models]
        except Exception as e:
            raise DatabaseError(
                message=f"Failed to get hooks by persona: {str(e)}",
                operation="get_hooks_by_persona",
            )

    async def get_hooks_by_type(self, hook_type: str) -> list[HookAnalysis]:
        """按钩子类型查询"""
        try:
            async with self.db.session() as session:
                result = await session.execute(
                    select(HookAnalysisModel)
                    .where(HookAnalysisModel.hook_type == hook_type)
                    .order_by(desc(HookAnalysisModel.created_at))
                )
                models = result.scalars().all()
            return [self._model_to_hook(m) for m in models]
        except Exception as e:
            raise DatabaseError(
                message=f"Failed to get hooks by type: {str(e)}",
                operation="get_hooks_by_type",
            )

    async def search_hooks(self, query: str, limit: int = 10) -> list[HookAnalysis]:
        """关键词搜索钩子分析"""
        try:
            async with self.db.session() as session:
                result = await session.execute(
                    select(HookAnalysisModel)
                    .where(
                        HookAnalysisModel.hook_text.contains(query)
                        | HookAnalysisModel.structural_formula.contains(query)
                    )
                    .order_by(desc(HookAnalysisModel.created_at))
                    .limit(limit)
                )
                models = result.scalars().all()
            return [self._model_to_hook(m) for m in models]
        except Exception as e:
            raise DatabaseError(
                message=f"Failed to search hooks: {str(e)}",
                operation="search_hooks",
            )

    async def get_hook_by_id(self, hook_id: str) -> HookAnalysis | None:
        """按 ID 获取钩子分析"""
        try:
            async with self.db.session() as session:
                result = await session.execute(
                    select(HookAnalysisModel).where(HookAnalysisModel.id == hook_id)
                )
                model = result.scalar_one_or_none()
            return self._model_to_hook(model) if model else None
        except Exception as e:
            raise DatabaseError(
                message=f"Failed to get hook by id: {str(e)}",
                operation="get_hook_by_id",
            )

    async def delete_hook(self, hook_id: str) -> bool:
        """删除钩子分析"""
        try:
            async with self.db.session() as session:
                result = await session.execute(
                    delete(HookAnalysisModel).where(HookAnalysisModel.id == hook_id)
                )
                await session.commit()
            return result.rowcount > 0
        except Exception as e:
            raise DatabaseError(
                message=f"Failed to delete hook: {str(e)}",
                operation="delete_hook",
            )

    # ── Topic Technique ──

    async def save_topic_technique(
        self, technique: TopicTechnique, persona_id: str
    ) -> str:
        """保存选题技法（upsert：存在则更新）"""
        try:
            async with self.db.session() as session:
                result = await session.execute(
                    select(TopicTechniqueModel)
                    .where(TopicTechniqueModel.persona_id == persona_id)
                )
                existing = result.scalar_one_or_none()

                if existing:
                    existing.angle_patterns = technique.angle_patterns
                    existing.pain_points = technique.pain_points
                    existing.topic_formulas = technique.topic_formulas
                    existing.selection_criteria = technique.selection_criteria
                    existing.avoid_patterns = technique.avoid_patterns
                    existing.updated_at = datetime.now()
                    tech_id = existing.id
                else:
                    tech_id = str(uuid.uuid4())
                    model = TopicTechniqueModel(
                        id=tech_id,
                        persona_id=persona_id,
                        angle_patterns=technique.angle_patterns,
                        pain_points=technique.pain_points,
                        topic_formulas=technique.topic_formulas,
                        selection_criteria=technique.selection_criteria,
                        avoid_patterns=technique.avoid_patterns,
                    )
                    session.add(model)

                await session.commit()
            logger.info(f"Topic technique saved: {tech_id} for persona {persona_id}")
            return tech_id
        except Exception as e:
            raise DatabaseError(
                message=f"Failed to save topic technique: {str(e)}",
                operation="save_topic_technique",
            )

    async def get_topic_technique(self, persona_id: str) -> TopicTechnique | None:
        """获取指定人格的选题技法"""
        try:
            async with self.db.session() as session:
                result = await session.execute(
                    select(TopicTechniqueModel)
                    .where(TopicTechniqueModel.persona_id == persona_id)
                )
                model = result.scalar_one_or_none()
            if not model:
                return None
            return TopicTechnique(
                angle_patterns=model.angle_patterns or [],
                pain_points=model.pain_points or [],
                topic_formulas=model.topic_formulas or [],
                selection_criteria=model.selection_criteria or [],
                avoid_patterns=model.avoid_patterns or [],
            )
        except Exception as e:
            raise DatabaseError(
                message=f"Failed to get topic technique: {str(e)}",
                operation="get_topic_technique",
            )

    # ── Content Structure ──

    async def save_content_structure(
        self, structure: ContentStructureMap
    ) -> str:
        """保存内容结构映射"""
        struct_id = structure.id or str(uuid.uuid4())
        try:
            async with self.db.session() as session:
                model = ContentStructureModel(
                    id=struct_id,
                    persona_id=structure.persona_id,
                    hook_id=structure.hook.id if structure.hook else None,
                    hook_text=structure.hook.hook_text if structure.hook else "",
                    hook_type=structure.hook.hook_type.value if structure.hook else "",
                    credibility_build=structure.credibility_build,
                    pain_amplification=structure.pain_amplification,
                    information_density_curve=structure.information_density_curve,
                    emotion_curve=structure.emotion_curve,
                    cta_pattern=structure.cta_pattern,
                    closing_emotion=structure.closing_emotion,
                    source_video_url=structure.source_video_url,
                    created_at=structure.created_at,
                )
                session.add(model)
                await session.commit()
            logger.info(f"Content structure saved: {struct_id}")
            return struct_id
        except Exception as e:
            raise DatabaseError(
                message=f"Failed to save content structure: {str(e)}",
                operation="save_content_structure",
            )

    async def get_structures_by_persona(
        self, persona_id: str
    ) -> list[ContentStructureMap]:
        """获取指定人格的所有内容结构映射"""
        try:
            async with self.db.session() as session:
                result = await session.execute(
                    select(ContentStructureModel)
                    .where(ContentStructureModel.persona_id == persona_id)
                    .order_by(desc(ContentStructureModel.created_at))
                )
                models = result.scalars().all()
            return [self._model_to_structure(m) for m in models]
        except Exception as e:
            raise DatabaseError(
                message=f"Failed to get structures by persona: {str(e)}",
                operation="get_structures_by_persona",
            )

    async def delete_structure(self, struct_id: str) -> bool:
        """删除内容结构映射"""
        try:
            async with self.db.session() as session:
                result = await session.execute(
                    delete(ContentStructureModel)
                    .where(ContentStructureModel.id == struct_id)
                )
                await session.commit()
            return result.rowcount > 0
        except Exception as e:
            raise DatabaseError(
                message=f"Failed to delete structure: {str(e)}",
                operation="delete_structure",
            )

    # ── Model Converters ──

    @staticmethod
    def _model_to_hook(model: HookAnalysisModel) -> HookAnalysis:
        return HookAnalysis(
            id=model.id,
            hook_text=model.hook_text,
            hook_type=HookType(model.hook_type),
            psychological_mechanism=model.psychological_mechanism,
            structural_formula=model.structural_formula,
            why_it_works=model.why_it_works,
            reconstruction_template=model.reconstruction_template,
            source_video_url=model.source_video_url,
            persona_id=model.persona_id,
            created_at=model.created_at,
        )

    @staticmethod
    def _model_to_structure(model: ContentStructureModel) -> ContentStructureMap:
        hook = HookAnalysis(
            hook_text=model.hook_text or "",
            hook_type=HookType(model.hook_type) if model.hook_type else HookType.REVERSE_LOGIC,
            psychological_mechanism="",
            structural_formula="",
            why_it_works="",
            reconstruction_template="",
        )
        return ContentStructureMap(
            id=model.id,
            hook=hook,
            credibility_build=model.credibility_build,
            pain_amplification=model.pain_amplification,
            information_density_curve=model.information_density_curve or [],
            emotion_curve=model.emotion_curve or [],
            cta_pattern=model.cta_pattern,
            closing_emotion=model.closing_emotion,
            persona_id=model.persona_id,
            source_video_url=model.source_video_url,
            created_at=model.created_at,
        )

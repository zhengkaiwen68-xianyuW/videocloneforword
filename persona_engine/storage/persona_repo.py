"""
人格仓储模块

提供人格画像的 CRUD 操作
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exceptions import PersonaNotFoundError, DatabaseError, StorageError
from ..core.types import (
    LogicArchitecture,
    PersonalityProfile,
    TemporalPattern,
)
from .database import database, PersonaModel


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
                    select(PersonaModel.id)
                )
                return len(result.scalars().all())
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
                # 查找所有超过阈值的 persona，在 Python 中过滤 processing 状态
                result = await session.execute(
                    select(PersonaModel).where(PersonaModel.created_at < cutoff_time)
                )
                all_stale = result.scalars().all()

                stale_models = [
                    m for m in all_stale
                    if (m.raw_json or {}).get("status") == "processing"
                ]

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
            raw_json=model.raw_json or {},
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

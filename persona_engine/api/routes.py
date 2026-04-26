"""
向后兼容层

聚合所有子路由为单一 router，保持 server.py 和 main.py 的现有 import 不变。
拆分后的独立模块：
- dependencies.py     共享实例
- models.py           Pydantic 模型
- background_tasks.py 后台任务函数
- routes_persona.py   人格 CRUD
- routes_rewrite.py   重写任务
- routes_tasks.py     任务管理
- routes_asr.py       ASR/视频处理
- routes_config.py    配置管理 + 健康检查
- routes_technique.py 技法提炼与查询
"""

from fastapi import APIRouter

from persona_engine.api.routes_persona import router as persona_router
from persona_engine.api.routes_rewrite import router as rewrite_router
from persona_engine.api.routes_tasks import router as tasks_router
from persona_engine.api.routes_asr import router as asr_router
from persona_engine.api.routes_config import router as config_router
from persona_engine.api.routes_technique import router as technique_router

# ── 向后兼容：汇总 router ──
router = APIRouter()
router.include_router(persona_router)
router.include_router(rewrite_router)
router.include_router(tasks_router)
router.include_router(asr_router)
router.include_router(config_router)
router.include_router(technique_router)

# ── 向后兼容：main.py 直接导入 video_task_repo ──
from persona_engine.api.dependencies import video_task_repo  # noqa: F401

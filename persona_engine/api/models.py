"""
请求/响应 Pydantic 模型

所有 API 端点的输入输出数据结构定义。
"""

from pydantic import BaseModel, Field


# ==================== 通用 ====================

class ErrorResponse(BaseModel):
    """错误响应"""
    error: str
    message: str
    code: str | None = None


# ==================== 人格管理 ====================

class PersonaResponse(BaseModel):
    """人格响应"""
    id: str
    name: str
    verbal_tics: list[str]
    grammar_prefs: list[str]
    logic_architecture: dict
    temporal_patterns: dict
    deep_psychology: dict
    raw_json: dict
    created_at: str
    updated_at: str


class PersonaListResponse(BaseModel):
    """人格列表响应"""
    personas: list[PersonaResponse]
    total: int


class PersonaCreateResponse(BaseModel):
    """创建人格响应"""
    id: str
    name: str
    message: str


# ==================== 重写任务 ====================

class RewriteRequestModel(BaseModel):
    """重写请求模型"""
    source_text: str = Field(..., min_length=1, description="原始素材文本")
    persona_ids: list[str] = Field(..., min_length=1, description="目标人格 ID 列表")
    locked_terms: list[str] = Field(default_factory=list, description="术语锚点")
    max_iterations: int = Field(default=5, ge=1, le=10, description="最大迭代次数")
    timeout_seconds: int = Field(default=300, ge=60, le=600, description="超时时间")


class BatchRewriteRequestModel(BaseModel):
    """批量洗稿请求模型"""
    source_texts: list[str] = Field(..., min_length=1, description="原始素材列表")
    persona_ids: list[str] = Field(..., min_length=1, description="人格 ID 列表")
    locked_terms: list[str] = Field(default_factory=list, description="术语锚点")
    max_iterations: int = Field(default=5, ge=1, le=10)
    timeout_seconds: int = Field(default=300, ge=60, le=600)


class BatchRewriteResponse(BaseModel):
    """批量洗稿响应"""
    batch_id: str
    task_ids: list[str]
    total_count: int


# ==================== 任务管理 ====================

class TaskStatusResponse(BaseModel):
    """任务状态响应"""
    task_id: str
    status: str
    iteration: int
    current_score: float
    best_score: float
    best_text: str
    history_count: int
    elapsed_seconds: float


class TaskResultResponse(BaseModel):
    """任务结果响应"""
    task_id: str
    status: str
    best_text: str
    best_score: float
    best_iteration: int
    completed_at: str | None


# ==================== ASR ====================

class BilibiliASRRequest(BaseModel):
    """B站视频ASR请求"""
    url: str | None = Field(None, description="单个B站视频链接")
    urls: list[str] | None = Field(None, description="多个B站视频链接列表")
    name: str | None = Field(None, description="可选的名称，用于创建人格")


class BilibiliASRResponse(BaseModel):
    """B站视频ASR响应"""
    task_id: str
    status: str
    total_videos: int = 0
    completed_videos: int = 0
    message: str


# ==================== 配置 ====================

class BilibiliConfigResponse(BaseModel):
    """B站配置响应"""
    cookie: str = ""
    access_token: str = ""
    min_interval: float = 3.0
    max_interval: float = 10.0
    delay_per_page: float = 5.0
    max_retries: int = 5
    retry_base_delay: float = 2.0
    user_agent: str = ""
    api_mode: str = "web"


class BilibiliConfigUpdateRequest(BaseModel):
    """B站配置更新请求"""
    cookie: str | None = None
    access_token: str | None = None
    min_interval: float | None = None
    max_interval: float | None = None
    delay_per_page: float | None = None
    max_retries: int | None = None
    retry_base_delay: float | None = None
    user_agent: str | None = None
    api_mode: str | None = None

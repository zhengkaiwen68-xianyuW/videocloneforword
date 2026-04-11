"""
核心数据结构定义 - 短视频人格深度重构与洗稿引擎
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class TaskStatus(str, Enum):
    """重写任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class ConsistencyScore(str, Enum):
    """一致性评分等级"""
    EXCELLENT = "excellent"   # >= 90
    GOOD = "good"            # 85-89
    FAIR = "fair"            # 80-84
    POOR = "poor"            # < 80


@dataclass
class WordTimestamp:
    """词级时间戳"""
    word: str
    start: float  # 秒
    end: float    # 秒

    @property
    def duration(self) -> float:
        """词持续时长（秒）"""
        return self.end - self.start


@dataclass
class PauseInfo:
    """静音/停顿信息"""
    start: float      # 停顿开始时间（秒）
    end: float        # 停顿结束时间（秒）
    duration: float   # 停顿时长（秒）
    after_word: str   # 停顿前的词
    pause_type: str = "NORMAL_PAUSE"  # 停顿类型: LONG_PAUSE / NORMAL_PAUSE

    @property
    def is_long_pause(self) -> bool:
        """是否为长停顿（>500ms）"""
        return self.duration > 0.5


@dataclass
class ASRResult:
    """ASR 语音转文字结果"""
    file_path: str                    # 原始文件路径
    text: str                         # 完整转写文本
    words: list[WordTimestamp]       # 词级时间戳
    wpm: float                        # 语速（词/分钟）
    pauses: list[PauseInfo]          # 静音/停顿列表
    total_duration: float             # 总音频时长（秒）
    speech_duration: float           # 有效语音时长（秒）
    language: str = "zh"             # 语言
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class TemporalPattern:
    """时间序列特征"""
    avg_pause_duration: float        # 平均停顿时长
    pause_frequency: float           # 停顿频率（次/分钟）
    speech_rhythm: str               # 节奏类型: fast/medium/slow
    excitement_curve: list[float]   # 兴奋度曲线


@dataclass
class LogicArchitecture:
    """逻辑架构特征"""
    opening_style: str               # 开场方式
    transition_patterns: list[str]   # 过渡模式
    closing_style: str                # 结尾方式
    topic_organization: str          # 话题组织方式


@dataclass
class DeepPsychology:
    """深度心理与修辞特征"""
    emotional_tone: str = "平稳中立"  # 如：亢奋、毒舌、爹味说教、温情
    emotional_arc: list[str] = field(default_factory=lambda: ["引入", "展开", "收尾"])
    rhetorical_devices: list[str] = field(default_factory=list)  # 如：反问句、排比
    lexicon: list[str] = field(default_factory=list)  # 专属高频词汇库 (实词)


@dataclass
class PersonalityProfile:
    """人格画像 (扩充版)"""
    id: str
    name: str                         # 作者名称
    verbal_tics: list[str]            # 口头禅列表
    grammar_prefs: list[str]          # 语法偏好
    logic_architecture: LogicArchitecture
    temporal_patterns: TemporalPattern
    deep_psychology: DeepPsychology = field(default_factory=DeepPsychology)  # 深度心理特征
    raw_json: dict = field(default_factory=dict)  # 原始 AI 输出（支持手动编辑）
    source_asr_texts: list[str] = field(default_factory=list)  # 原始 ASR 文本（12篇）
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "verbal_tics": self.verbal_tics,
            "grammar_prefs": self.grammar_prefs,
            "logic_architecture": {
                "opening_style": self.logic_architecture.opening_style,
                "transition_patterns": self.logic_architecture.transition_patterns,
                "closing_style": self.logic_architecture.closing_style,
                "topic_organization": self.logic_architecture.topic_organization,
            },
            "temporal_patterns": {
                "avg_pause_duration": self.temporal_patterns.avg_pause_duration,
                "pause_frequency": self.temporal_patterns.pause_frequency,
                "speech_rhythm": self.temporal_patterns.speech_rhythm,
                "excitement_curve": self.temporal_patterns.excitement_curve,
            },
            "deep_psychology": {
                "emotional_tone": self.deep_psychology.emotional_tone,
                "emotional_arc": self.deep_psychology.emotional_arc,
                "rhetorical_devices": self.deep_psychology.rhetorical_devices,
                "lexicon": self.deep_psychology.lexicon,
            },
            "raw_json": self.raw_json,
            "source_asr_texts": self.source_asr_texts,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class VersionEntry:
    """版本历史条目"""
    version: int                      # 版本号
    text: str                         # 重写文本
    consistency_score: float         # 一致性评分
    iteration: int                    # 迭代次数
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class RewriteRequest:
    """重写请求"""
    source_text: str                  # 原始素材
    persona_ids: list[str]            # 目标人格 ID 列表
    locked_terms: list[str]          # 术语锚点（需保护）
    max_iterations: int = 5          # 最大迭代次数
    timeout_seconds: int = 300       # 超时时间（5分钟）
    model_provider: str = "minimax"   # 模型提供商


@dataclass
class RewriteResult:
    """重写结果"""
    task_id: str
    status: TaskStatus
    final_text: str                   # 最终文本
    best_text: str                   # 最佳版本（最高分）
    iteration: int                   # 当前迭代
    consistency_score: float         # 当前评分
    history_versions: list[VersionEntry]  # 历史版本
    locked_terms_preserved: bool     # 术语是否保留
    started_at: datetime
    completed_at: datetime | None = None
    error_message: str | None = None

    @property
    def is_success(self) -> bool:
        return self.status == TaskStatus.COMPLETED

    @property
    def best_score(self) -> float:
        """历史最高分"""
        if not self.history_versions:
            return 0.0
        return max(v.consistency_score for v in self.history_versions)


@dataclass
class TaskStatusResponse:
    """任务状态查询响应"""
    task_id: str
    status: TaskStatus
    iteration: int
    current_score: float
    best_score: float
    best_text: str
    history_count: int
    elapsed_seconds: float
    estimated_remaining: float | None = None


@dataclass
class BatchRewriteRequest:
    """批量洗稿请求"""
    source_texts: list[str]           # 多条原始素材
    persona_ids: list[str]           # 人格 ID 列表
    locked_terms: list[str]          # 术语锚点
    max_iterations: int = 5
    timeout_seconds: int = 300
    model_provider: str = "minimax"


@dataclass
class BatchRewriteResponse:
    """批量洗稿响应"""
    batch_id: str
    task_ids: list[str]              # 各个任务 ID
    total_count: int
    completed_count: int = 0
    failed_count: int = 0


@dataclass
class PersonaCreateRequest:
    """创建人格请求"""
    name: str                         # 作者名称
    source_texts: list[str] = None    # ASR 原文（可选，与 video_urls 二选一）
    video_urls: list[str] = None      # B站视频链接列表（可选，与 source_texts 二选一）


@dataclass
class PersonaUpdateRequest:
    """更新人格请求"""
    verbal_tics: list[str] | None = None
    grammar_prefs: list[str] | None = None
    logic_architecture: LogicArchitecture | None = None
    temporal_patterns: TemporalPattern | None = None


@dataclass
class PersonaAddVideosRequest:
    """向已有人格追加视频请求"""
    video_urls: list[str]              # B站视频链接列表


# ========== 异常类型定义 ==========

class PersonaEngineException(Exception):
    """基础异常类"""
    def __init__(self, message: str, code: str | None = None):
        self.message = message
        self.code = code
        super().__init__(self.message)


class ASRError(PersonaEngineException):
    """ASR 相关错误"""
    pass


class TranscriptionError(ASRError):
    """转写失败"""
    pass


class PersonalityExtractionError(ASRError):
    """人格提取失败"""
    pass


class RewriteError(PersonaEngineException):
    """重写相关错误"""
    pass


class ModelAPIError(RewriteError):
    """模型 API 调用错误"""
    pass


class TermLockError(RewriteError):
    """术语锁定错误"""
    pass


class AuditError(PersonaEngineException):
    """审计相关错误"""
    pass


class ConsistencyScoreError(AuditError):
    """评分计算错误"""
    pass


class IterationTimeoutError(AuditError):
    """迭代超时"""
    pass


class StorageError(PersonaEngineException):
    """存储相关错误"""
    pass


class PersonaNotFoundError(StorageError):
    """人格不存在"""
    pass


class TaskNotFoundError(StorageError):
    """任务不存在"""
    pass

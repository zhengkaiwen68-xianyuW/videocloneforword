"""
自定义异常定义 - 短视频人格深度重构与洗稿引擎
"""


class PersonaEngineException(Exception):
    """基础异常类"""

    def __init__(self, message: str, code: str | None = None, details: dict | None = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "code": self.code,
            "details": self.details,
        }


# ========== ASR 相关异常 ==========

class ASRError(PersonaEngineException):
    """ASR 相关错误基类"""
    pass


class TranscriptionError(ASRError):
    """语音转写失败"""

    def __init__(self, message: str, file_path: str | None = None, details: dict | None = None):
        super().__init__(
            message=message,
            code="TRANSCRIPTION_ERROR",
            details={**(details or {}), "file_path": file_path},
        )


class AudioFileNotFoundError(ASRError):
    """音频文件不存在"""

    def __init__(self, file_path: str):
        super().__init__(
            message=f"Audio file not found: {file_path}",
            code="AUDIO_FILE_NOT_FOUND",
            details={"file_path": file_path},
        )


class UnsupportedAudioFormatError(ASRError):
    """不支持的音频格式"""

    def __init__(self, file_path: str, supported_formats: list[str] | None = None):
        super().__init__(
            message=f"Unsupported audio format: {file_path}",
            code="UNSUPPORTED_AUDIO_FORMAT",
            details={
                "file_path": file_path,
                "supported_formats": supported_formats or [".mp3", ".mp4", ".wav", ".m4a"],
            },
        )


class PersonalityExtractionError(ASRError):
    """人格特征提取失败"""

    def __init__(self, message: str, texts_count: int = 0, details: dict | None = None):
        super().__init__(
            message=message,
            code="PERSONALITY_EXTRACTION_ERROR",
            details={**(details or {}), "texts_count": texts_count},
        )


class BilibiliDownloadError(ASRError):
    """B站视频下载失败"""

    def __init__(self, message: str, url: str | None = None, details: dict | None = None):
        super().__init__(
            message=message,
            code="BILIBILI_DOWNLOAD_ERROR",
            details={**(details or {}), "url": url},
        )


class AudioExtractionError(ASRError):
    """音频提取失败"""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(
            message=message,
            code="AUDIO_EXTRACTION_ERROR",
            details=details or {},
        )


# ========== 重写引擎相关异常 ==========

class RewriteError(PersonaEngineException):
    """重写相关错误基类"""
    pass


class ModelAPIError(RewriteError):
    """模型 API 调用错误"""

    def __init__(
        self,
        message: str,
        provider: str | None = None,
        status_code: int | None = None,
        details: dict | None = None,
    ):
        super().__init__(
            message=message,
            code="MODEL_API_ERROR",
            details={
                **(details or {}),
                "provider": provider,
                "status_code": status_code,
            },
        )


class JSONParseError(RewriteError):
    """JSON 解析失败"""

    def __init__(self, message: str, raw_response: str | None = None, details: dict | None = None):
        super().__init__(
            message=message,
            code="JSON_PARSE_ERROR",
            details={**(details or {}), "raw_response": raw_response[:500] if raw_response else None},
        )


class TermLockError(RewriteError):
    """术语锁定错误"""

    def __init__(self, message: str, violated_terms: list[str] | None = None, details: dict | None = None):
        super().__init__(
            message=message,
            code="TERM_LOCK_ERROR",
            details={**(details or {}), "violated_terms": violated_terms or []},
        )


class PersonaInjectionError(RewriteError):
    """人格注入失败"""

    def __init__(self, message: str, persona_id: str | None = None, details: dict | None = None):
        super().__init__(
            message=message,
            code="PERSONA_INJECTION_ERROR",
            details={**(details or {}), "persona_id": persona_id},
        )


# ========== 审计系统相关异常 ==========

class AuditError(PersonaEngineException):
    """审计相关错误基类"""
    pass


class ConsistencyScoreError(AuditError):
    """一致性评分计算错误"""

    def __init__(self, message: str, score: float | None = None, details: dict | None = None):
        super().__init__(
            message=message,
            code="CONSISTENCY_SCORE_ERROR",
            details={**(details or {}), "score": score},
        )


class ReverseExtractionError(AuditError):
    """反向推导失败"""

    def __init__(self, message: str, text_length: int = 0, details: dict | None = None):
        super().__init__(
            message=message,
            code="REVERSE_EXTRACTION_ERROR",
            details={**(details or {}), "text_length": text_length},
        )


class IterationTimeoutError(AuditError):
    """迭代超时"""

    def __init__(
        self,
        message: str,
        iteration: int = 0,
        elapsed_seconds: float = 0,
        max_iterations: int = 5,
        timeout_seconds: int = 300,
        details: dict | None = None,
    ):
        super().__init__(
            message=message,
            code="ITERATION_TIMEOUT",
            details={
                **(details or {}),
                "iteration": iteration,
                "elapsed_seconds": elapsed_seconds,
                "max_iterations": max_iterations,
                "timeout_seconds": timeout_seconds,
            },
        )


# ========== 存储相关异常 ==========

class StorageError(PersonaEngineException):
    """存储相关错误基类"""
    pass


class PersonaNotFoundError(StorageError):
    """人格不存在"""

    def __init__(self, persona_id: str):
        super().__init__(
            message=f"Persona not found: {persona_id}",
            code="PERSONA_NOT_FOUND",
            details={"persona_id": persona_id},
        )


class TaskNotFoundError(StorageError):
    """任务不存在"""

    def __init__(self, task_id: str):
        super().__init__(
            message=f"Task not found: {task_id}",
            code="TASK_NOT_FOUND",
            details={"task_id": task_id},
        )


class DatabaseError(StorageError):
    """数据库操作错误"""

    def __init__(self, message: str, operation: str | None = None, details: dict | None = None):
        super().__init__(
            message=message,
            code="DATABASE_ERROR",
            details={**(details or {}), "operation": operation},
        )


# ========== API 相关异常 ==========

class APIError(PersonaEngineException):
    """API 相关错误基类"""
    pass


class ValidationError(APIError):
    """请求验证失败"""

    def __init__(self, message: str, field: str | None = None, details: dict | None = None):
        super().__init__(
            message=message,
            code="VALIDATION_ERROR",
            details={**(details or {}), "field": field},
        )


class RateLimitError(APIError):
    """请求频率限制"""

    def __init__(self, message: str = "Rate limit exceeded", retry_after: int | None = None):
        super().__init__(
            message=message,
            code="RATE_LIMIT_ERROR",
            details={"retry_after": retry_after},
        )

"""
Tests for core/exceptions.py - exception classes
"""
import pytest

import sys
sys.path.insert(0, '..')

from persona_engine.core.exceptions import (
    PersonaEngineException,
    ASRError,
    TranscriptionError,
    AudioFileNotFoundError,
    UnsupportedAudioFormatError,
    PersonalityExtractionError,
    BilibiliDownloadError,
    AudioExtractionError,
    RewriteError,
    ModelAPIError,
    JSONParseError,
    TermLockError,
    PersonaInjectionError,
    AuditError,
    ConsistencyScoreError,
    ReverseExtractionError,
    IterationTimeoutError,
    StorageError,
    PersonaNotFoundError,
    TaskNotFoundError,
    DatabaseError,
    APIError,
    ValidationError,
    RateLimitError,
)


class TestPersonaEngineException:
    """PersonaEngineException base class tests"""

    def test_creation_with_message(self):
        """Test basic exception creation"""
        exc = PersonaEngineException("Test error message")
        assert exc.message == "Test error message"
        assert exc.code is None
        assert exc.details == {}

    def test_creation_with_code(self):
        """Test exception creation with code"""
        exc = PersonaEngineException("Test error", code="TEST_CODE")
        assert exc.message == "Test error"
        assert exc.code == "TEST_CODE"

    def test_creation_with_details(self):
        """Test exception creation with details"""
        exc = PersonaEngineException("Test error", details={"key": "value"})
        assert exc.details == {"key": "value"}

    def test_to_dict(self):
        """Test to_dict method"""
        exc = PersonaEngineException(
            "Test error",
            code="TEST_CODE",
            details={"key": "value"}
        )
        d = exc.to_dict()

        assert d["error"] == "PersonaEngineException"
        assert d["message"] == "Test error"
        assert d["code"] == "TEST_CODE"
        assert d["details"] == {"key": "value"}

    def test_inheritance(self):
        """Test that it inherits from Exception"""
        exc = PersonaEngineException("test")
        assert isinstance(exc, Exception)


class TestASRError:
    """ASRError tests"""

    def test_creation(self):
        """Test ASRError creation"""
        exc = ASRError("ASR error occurred")
        assert exc.message == "ASR error occurred"


class TestTranscriptionError:
    """TranscriptionError tests"""

    def test_creation(self):
        """Test TranscriptionError creation"""
        exc = TranscriptionError("Transcription failed", file_path="/path/to/file.mp3")
        assert exc.message == "Transcription failed"
        assert exc.code == "TRANSCRIPTION_ERROR"
        assert exc.details["file_path"] == "/path/to/file.mp3"

    def test_creation_with_additional_details(self):
        """Test TranscriptionError with additional details"""
        exc = TranscriptionError(
            "Transcription failed",
            file_path="/path/to/file.mp3",
            details={"duration": 60}
        )
        assert exc.details["file_path"] == "/path/to/file.mp3"
        assert exc.details["duration"] == 60


class TestAudioFileNotFoundError:
    """AudioFileNotFoundError tests"""

    def test_creation(self):
        """Test AudioFileNotFoundError creation"""
        exc = AudioFileNotFoundError("/path/to/audio.mp3")
        assert exc.code == "AUDIO_FILE_NOT_FOUND"
        assert exc.details["file_path"] == "/path/to/audio.mp3"


class TestUnsupportedAudioFormatError:
    """UnsupportedAudioFormatError tests"""

    def test_creation(self):
        """Test UnsupportedAudioFormatError creation"""
        exc = UnsupportedAudioFormatError("/path/to/file.xyz")
        assert exc.code == "UNSUPPORTED_AUDIO_FORMAT"

    def test_creation_with_supported_formats(self):
        """Test with custom supported formats"""
        exc = UnsupportedAudioFormatError(
            "/path/to/file.xyz",
            supported_formats=[".mp3", ".wav", ".flac"]
        )
        assert ".mp3" in exc.details["supported_formats"]


class TestPersonalityExtractionError:
    """PersonalityExtractionError tests"""

    def test_creation(self):
        """Test PersonalityExtractionError creation"""
        exc = PersonalityExtractionError("Extraction failed", texts_count=5)
        assert exc.code == "PERSONALITY_EXTRACTION_ERROR"
        assert exc.details["texts_count"] == 5


class TestBilibiliDownloadError:
    """BilibiliDownloadError tests"""

    def test_creation_not_retryable(self):
        """Test creation without retry flag"""
        exc = BilibiliDownloadError("Download failed", url="https://b23.tv/abc")
        assert exc.code == "BILIBILI_DOWNLOAD_ERROR"
        assert exc.retryable is False

    def test_creation_retryable(self):
        """Test creation with retryable flag"""
        exc = BilibiliDownloadError(
            "Rate limited",
            url="https://b23.tv/abc",
            retryable=True
        )
        assert exc.retryable is True

    def test_creation_with_details(self):
        """Test creation with additional details"""
        exc = BilibiliDownloadError(
            "Download failed",
            url="https://b23.tv/abc",
            details={"error_code": 403}
        )
        assert exc.details["url"] == "https://b23.tv/abc"
        assert exc.details["error_code"] == 403


class TestAudioExtractionError:
    """AudioExtractionError tests"""

    def test_creation(self):
        """Test AudioExtractionError creation"""
        exc = AudioExtractionError("Audio extraction failed")
        assert exc.code == "AUDIO_EXTRACTION_ERROR"


class TestRewriteError:
    """RewriteError tests"""

    def test_creation(self):
        """Test RewriteError creation"""
        exc = RewriteError("Rewrite failed")
        assert exc.message == "Rewrite failed"


class TestModelAPIError:
    """ModelAPIError tests"""

    def test_creation(self):
        """Test ModelAPIError creation"""
        exc = ModelAPIError("API call failed", provider="minimax")
        assert exc.code == "MODEL_API_ERROR"
        assert exc.details["provider"] == "minimax"

    def test_creation_with_status_code(self):
        """Test with HTTP status code"""
        exc = ModelAPIError(
            "API call failed",
            provider="openai",
            status_code=500
        )
        assert exc.details["status_code"] == 500


class TestJSONParseError:
    """JSONParseError tests"""

    def test_creation(self):
        """Test JSONParseError creation"""
        exc = JSONParseError("JSON parse failed", raw_response='{"invalid": ')
        assert exc.code == "JSON_PARSE_ERROR"
        # Should truncate long responses
        assert len(exc.details["raw_response"]) <= 500


class TestTermLockError:
    """TermLockError tests"""

    def test_creation(self):
        """Test TermLockError creation"""
        exc = TermLockError("Term lock violated", violated_terms=["术语1", "术语2"])
        assert exc.code == "TERM_LOCK_ERROR"
        assert "术语1" in exc.details["violated_terms"]
        assert "术语2" in exc.details["violated_terms"]


class TestPersonaInjectionError:
    """PersonaInjectionError tests"""

    def test_creation(self):
        """Test PersonaInjectionError creation"""
        exc = PersonaInjectionError("Injection failed", persona_id="persona-001")
        assert exc.code == "PERSONA_INJECTION_ERROR"
        assert exc.details["persona_id"] == "persona-001"


class TestAuditError:
    """AuditError tests"""

    def test_creation(self):
        """Test AuditError creation"""
        exc = AuditError("Audit failed")
        assert exc.message == "Audit failed"


class TestConsistencyScoreError:
    """ConsistencyScoreError tests"""

    def test_creation(self):
        """Test ConsistencyScoreError creation"""
        exc = ConsistencyScoreError("Scoring failed", score=45.5)
        assert exc.code == "CONSISTENCY_SCORE_ERROR"
        assert exc.details["score"] == 45.5


class TestReverseExtractionError:
    """ReverseExtractionError tests"""

    def test_creation(self):
        """Test ReverseExtractionError creation"""
        exc = ReverseExtractionError("Reverse extraction failed", text_length=100)
        assert exc.code == "REVERSE_EXTRACTION_ERROR"
        assert exc.details["text_length"] == 100


class TestIterationTimeoutError:
    """IterationTimeoutError tests"""

    def test_creation(self):
        """Test IterationTimeoutError creation"""
        exc = IterationTimeoutError(
            "Iteration timed out",
            iteration=5,
            elapsed_seconds=300.0,
            max_iterations=5,
            timeout_seconds=300
        )
        assert exc.code == "ITERATION_TIMEOUT"
        assert exc.details["iteration"] == 5
        assert exc.details["elapsed_seconds"] == 300.0
        assert exc.details["max_iterations"] == 5
        assert exc.details["timeout_seconds"] == 300


class TestStorageError:
    """StorageError tests"""

    def test_creation(self):
        """Test StorageError creation"""
        exc = StorageError("Storage operation failed")
        assert exc.message == "Storage operation failed"


class TestPersonaNotFoundError:
    """PersonaNotFoundError tests"""

    def test_creation(self):
        """Test PersonaNotFoundError creation"""
        exc = PersonaNotFoundError("persona-123")
        assert exc.code == "PERSONA_NOT_FOUND"
        assert exc.details["persona_id"] == "persona-123"


class TestTaskNotFoundError:
    """TaskNotFoundError tests"""

    def test_creation(self):
        """Test TaskNotFoundError creation"""
        exc = TaskNotFoundError("task-456")
        assert exc.code == "TASK_NOT_FOUND"
        assert exc.details["task_id"] == "task-456"


class TestDatabaseError:
    """DatabaseError tests"""

    def test_creation(self):
        """Test DatabaseError creation"""
        exc = DatabaseError("Database operation failed", operation="SELECT")
        assert exc.code == "DATABASE_ERROR"
        assert exc.details["operation"] == "SELECT"


class TestAPIError:
    """APIError tests"""

    def test_creation(self):
        """Test APIError creation"""
        exc = APIError("API error occurred")
        assert exc.message == "API error occurred"


class TestValidationError:
    """ValidationError tests"""

    def test_creation(self):
        """Test ValidationError creation"""
        exc = ValidationError("Validation failed", field="source_text")
        assert exc.code == "VALIDATION_ERROR"
        assert exc.details["field"] == "source_text"


class TestRateLimitError:
    """RateLimitError tests"""

    def test_creation_default(self):
        """Test RateLimitError with defaults"""
        exc = RateLimitError()
        assert exc.code == "RATE_LIMIT_ERROR"
        assert exc.details["retry_after"] is None

    def test_creation_with_retry_after(self):
        """Test RateLimitError with retry_after"""
        exc = RateLimitError(retry_after=60)
        assert exc.details["retry_after"] == 60


class TestExceptionInheritance:
    """Test exception class hierarchy"""

    def test_asr_errors_inherit_from_base(self):
        """Test ASR-related errors inherit from PersonaEngineException"""
        assert issubclass(ASRError, PersonaEngineException)
        assert issubclass(TranscriptionError, ASRError)
        assert issubclass(PersonalityExtractionError, ASRError)
        assert issubclass(BilibiliDownloadError, ASRError)
        assert issubclass(AudioExtractionError, ASRError)

    def test_rewrite_errors_inherit_from_base(self):
        """Test Rewrite-related errors inherit from PersonaEngineException"""
        assert issubclass(RewriteError, PersonaEngineException)
        assert issubclass(ModelAPIError, RewriteError)
        assert issubclass(JSONParseError, RewriteError)
        assert issubclass(TermLockError, RewriteError)
        assert issubclass(PersonaInjectionError, RewriteError)

    def test_audit_errors_inherit_from_base(self):
        """Test Audit-related errors inherit from PersonaEngineException"""
        assert issubclass(AuditError, PersonaEngineException)
        assert issubclass(ConsistencyScoreError, AuditError)
        assert issubclass(ReverseExtractionError, AuditError)
        assert issubclass(IterationTimeoutError, AuditError)

    def test_storage_errors_inherit_from_base(self):
        """Test Storage-related errors inherit from PersonaEngineException"""
        assert issubclass(StorageError, PersonaEngineException)
        assert issubclass(PersonaNotFoundError, StorageError)
        assert issubclass(TaskNotFoundError, StorageError)
        assert issubclass(DatabaseError, StorageError)

    def test_api_errors_inherit_from_base(self):
        """Test API-related errors inherit from PersonaEngineException"""
        assert issubclass(APIError, PersonaEngineException)
        assert issubclass(ValidationError, APIError)
        assert issubclass(RateLimitError, APIError)

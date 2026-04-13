"""
Tests for core/types.py - data classes and enums
"""
import pytest
from datetime import datetime

from persona_engine.core.types import (
    TaskStatus,
    ConsistencyScore,
    WordTimestamp,
    PauseInfo,
    ASRResult,
    TemporalPattern,
    LogicArchitecture,
    DeepPsychology,
    PersonalityProfile,
    VersionEntry,
    RewriteRequest,
    RewriteResult,
    TaskStatusResponse,
)


class TestTaskStatus:
    """TaskStatus enum tests"""

    def test_task_status_values(self):
        """Test TaskStatus enum values"""
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.RUNNING.value == "running"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"
        assert TaskStatus.TIMEOUT.value == "timeout"

    def test_task_status_is_string(self):
        """Test TaskStatus is a string enum"""
        assert isinstance(TaskStatus.PENDING, str)


class TestConsistencyScore:
    """ConsistencyScore enum tests"""

    def test_consistency_score_values(self):
        """Test ConsistencyScore enum values"""
        assert ConsistencyScore.EXCELLENT.value == "excellent"
        assert ConsistencyScore.GOOD.value == "good"
        assert ConsistencyScore.FAIR.value == "fair"
        assert ConsistencyScore.POOR.value == "poor"


class TestWordTimestamp:
    """WordTimestamp dataclass tests"""

    def test_creation(self):
        """Test WordTimestamp creation"""
        wt = WordTimestamp(word="测试", start=0.0, end=1.5)
        assert wt.word == "测试"
        assert wt.start == 0.0
        assert wt.end == 1.5

    def test_duration_property(self):
        """Test duration property"""
        wt = WordTimestamp(word="测试", start=1.0, end=3.5)
        assert wt.duration == 2.5

    def test_duration_zero(self):
        """Test zero duration"""
        wt = WordTimestamp(word="测试", start=5.0, end=5.0)
        assert wt.duration == 0.0


class TestPauseInfo:
    """PauseInfo dataclass tests"""

    def test_creation(self):
        """Test PauseInfo creation"""
        pause = PauseInfo(
            start=1.0,
            end=1.5,
            duration=0.5,
            after_word="测试",
            pause_type="NORMAL_PAUSE"
        )
        assert pause.start == 1.0
        assert pause.end == 1.5
        assert pause.duration == 0.5
        assert pause.after_word == "测试"
        assert pause.pause_type == "NORMAL_PAUSE"

    def test_is_long_pause_true(self):
        """Test is_long_pause returns True for > 500ms"""
        pause = PauseInfo(
            start=1.0,
            end=1.6,
            duration=0.6,
            after_word="测试",
        )
        assert pause.is_long_pause is True

    def test_is_long_pause_false(self):
        """Test is_long_pause returns False for <= 500ms"""
        pause = PauseInfo(
            start=1.0,
            end=1.4,
            duration=0.4,
            after_word="测试",
        )
        assert pause.is_long_pause is False

    def test_default_pause_type(self):
        """Test default pause_type is NORMAL_PAUSE"""
        pause = PauseInfo(
            start=1.0,
            end=1.3,
            duration=0.3,
            after_word="测试",
        )
        assert pause.pause_type == "NORMAL_PAUSE"


class TestTemporalPattern:
    """TemporalPattern dataclass tests"""

    def test_creation(self):
        """Test TemporalPattern creation"""
        pattern = TemporalPattern(
            avg_pause_duration=0.5,
            pause_frequency=10.0,
            speech_rhythm="medium",
            excitement_curve=[0.5, 0.7, 0.8, 0.6]
        )
        assert pattern.avg_pause_duration == 0.5
        assert pattern.pause_frequency == 10.0
        assert pattern.speech_rhythm == "medium"
        assert len(pattern.excitement_curve) == 4


class TestLogicArchitecture:
    """LogicArchitecture dataclass tests"""

    def test_creation(self):
        """Test LogicArchitecture creation"""
        arch = LogicArchitecture(
            opening_style="悬念开场",
            transition_patterns=["因果", "对比"],
            closing_style="总结升华",
            topic_organization="递进式"
        )
        assert arch.opening_style == "悬念开场"
        assert len(arch.transition_patterns) == 2
        assert arch.closing_style == "总结升华"
        assert arch.topic_organization == "递进式"


class TestDeepPsychology:
    """DeepPsychology dataclass tests"""

    def test_creation_with_defaults(self):
        """Test DeepPsychology creation with default values"""
        dp = DeepPsychology()
        assert dp.emotional_tone == "平稳中立"
        assert dp.emotional_arc == ["引入", "展开", "收尾"]
        assert dp.rhetorical_devices == []
        assert dp.lexicon == []

    def test_creation_with_values(self):
        """Test DeepPsychology creation with custom values"""
        dp = DeepPsychology(
            emotional_tone="亢奋",
            emotional_arc=["开场", "高潮", "结尾"],
            rhetorical_devices=["反问句", "排比"],
            lexicon=["绝对零度", "极限操作"]
        )
        assert dp.emotional_tone == "亢奋"
        assert len(dp.emotional_arc) == 3
        assert len(dp.rhetorical_devices) == 2


class TestPersonalityProfile:
    """PersonalityProfile dataclass tests"""

    def _create_profile(self) -> PersonalityProfile:
        """Helper to create a valid profile"""
        return PersonalityProfile(
            id="test-profile-001",
            name="测试人格",
            verbal_tics=["那么", "其实"],
            grammar_prefs=["使用短句", "口语化"],
            logic_architecture=LogicArchitecture(
                opening_style="悬念开场",
                transition_patterns=["因果"],
                closing_style="总结",
                topic_organization="递进式"
            ),
            temporal_patterns=TemporalPattern(
                avg_pause_duration=0.5,
                pause_frequency=10.0,
                speech_rhythm="medium",
                excitement_curve=[0.5, 0.7]
            ),
            deep_psychology=DeepPsychology(
                emotional_tone="活泼",
                emotional_arc=["引入", "展开"],
                rhetorical_devices=["反问句"],
                lexicon=["厉害", "牛"]
            ),
            raw_json={"status": "completed"},
            source_asr_texts=["原文1", "原文2"],
        )

    def test_creation(self):
        """Test PersonalityProfile creation"""
        profile = self._create_profile()
        assert profile.id == "test-profile-001"
        assert profile.name == "测试人格"
        assert len(profile.verbal_tics) == 2
        assert len(profile.grammar_prefs) == 2

    def test_to_dict(self):
        """Test to_dict method"""
        profile = self._create_profile()
        d = profile.to_dict()

        assert d["id"] == "test-profile-001"
        assert d["name"] == "测试人格"
        assert "verbal_tics" in d
        assert "logic_architecture" in d
        assert "temporal_patterns" in d
        assert "deep_psychology" in d
        assert d["raw_json"] == {"status": "completed"}
        assert len(d["source_asr_texts"]) == 2

    def test_to_dict_datetime_serialization(self):
        """Test that datetime is serialized to isoformat"""
        profile = self._create_profile()
        d = profile.to_dict()

        assert "created_at" in d
        assert "updated_at" in d
        # Should be ISO format string, not datetime object
        assert isinstance(d["created_at"], str)

    def test_created_at_default(self):
        """Test created_at has a default value"""
        profile = PersonalityProfile(
            id="test",
            name="Test",
            verbal_tics=[],
            grammar_prefs=[],
            logic_architecture=LogicArchitecture(
                opening_style="",
                transition_patterns=[],
                closing_style="",
                topic_organization=""
            ),
            temporal_patterns=TemporalPattern(
                avg_pause_duration=0.0,
                pause_frequency=0.0,
                speech_rhythm="medium",
                excitement_curve=[]
            ),
            deep_psychology=DeepPsychology(),
        )
        assert profile.created_at is not None
        assert isinstance(profile.created_at, datetime)


class TestVersionEntry:
    """VersionEntry dataclass tests"""

    def test_creation(self):
        """Test VersionEntry creation"""
        entry = VersionEntry(
            version=1,
            text="重写文本",
            consistency_score=85.5,
            iteration=3
        )
        assert entry.version == 1
        assert entry.text == "重写文本"
        assert entry.consistency_score == 85.5
        assert entry.iteration == 3

    def test_created_at_default(self):
        """Test created_at has a default value"""
        entry = VersionEntry(
            version=1,
            text="文本",
            consistency_score=80.0,
            iteration=1
        )
        assert entry.created_at is not None
        assert isinstance(entry.created_at, datetime)


class TestRewriteRequest:
    """RewriteRequest dataclass tests"""

    def test_creation_with_defaults(self):
        """Test RewriteRequest creation with default values"""
        request = RewriteRequest(
            source_text="原始文本",
            persona_ids=["persona-1", "persona-2"],
            locked_terms=["术语1"]
        )
        assert request.source_text == "原始文本"
        assert len(request.persona_ids) == 2
        assert request.locked_terms == ["术语1"]
        assert request.max_iterations == 5
        assert request.timeout_seconds == 300
        assert request.model_provider == "minimax"

    def test_creation_with_custom_values(self):
        """Test RewriteRequest creation with custom values"""
        request = RewriteRequest(
            source_text="原始文本",
            persona_ids=["persona-1"],
            locked_terms=["术语"],
            max_iterations=10,
            timeout_seconds=600,
            model_provider="openai"
        )
        assert request.max_iterations == 10
        assert request.timeout_seconds == 600
        assert request.model_provider == "openai"


class TestRewriteResult:
    """RewriteResult dataclass tests"""

    def _create_result(self) -> RewriteResult:
        """Helper to create a valid result"""
        return RewriteResult(
            task_id="task-001",
            status=TaskStatus.COMPLETED,
            final_text="最终文本",
            best_text="最佳文本",
            iteration=3,
            consistency_score=88.0,
            history_versions=[
                VersionEntry(version=1, text="版本1", consistency_score=70.0, iteration=1),
                VersionEntry(version=2, text="版本2", consistency_score=85.0, iteration=2),
            ],
            locked_terms_preserved=True,
            started_at=datetime.now(),
            completed_at=datetime.now(),
        )

    def test_creation(self):
        """Test RewriteResult creation"""
        result = self._create_result()
        assert result.task_id == "task-001"
        assert result.status == TaskStatus.COMPLETED
        assert result.iteration == 3
        assert len(result.history_versions) == 2

    def test_is_success_property(self):
        """Test is_success property"""
        completed_result = self._create_result()
        assert completed_result.is_success is True

        failed_result = RewriteResult(
            task_id="task-002",
            status=TaskStatus.FAILED,
            final_text="",
            best_text="",
            iteration=0,
            consistency_score=0.0,
            history_versions=[],
            locked_terms_preserved=False,
            started_at=datetime.now(),
        )
        assert failed_result.is_success is False

    def test_best_score_property(self):
        """Test best_score property"""
        result = self._create_result()
        assert result.best_score == 85.0  # Max of 70.0 and 85.0

    def test_best_score_empty_history(self):
        """Test best_score with empty history"""
        result = RewriteResult(
            task_id="task-003",
            status=TaskStatus.RUNNING,
            final_text="",
            best_text="",
            iteration=0,
            consistency_score=0.0,
            history_versions=[],
            locked_terms_preserved=False,
            started_at=datetime.now(),
        )
        assert result.best_score == 0.0


class TestTaskStatusResponse:
    """TaskStatusResponse dataclass tests"""

    def test_creation(self):
        """Test TaskStatusResponse creation"""
        response = TaskStatusResponse(
            task_id="task-001",
            status=TaskStatus.RUNNING,
            iteration=2,
            current_score=75.0,
            best_score=85.0,
            best_text="最佳文本",
            history_count=2,
            elapsed_seconds=30.5,
            estimated_remaining=60.0
        )
        assert response.task_id == "task-001"
        assert response.status == TaskStatus.RUNNING
        assert response.iteration == 2
        assert response.current_score == 75.0
        assert response.best_score == 85.0
        assert response.estimated_remaining == 60.0

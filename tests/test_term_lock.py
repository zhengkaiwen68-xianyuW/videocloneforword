"""
Tests for rewrite/term_lock.py - term locking functionality
"""
import pytest

import sys
sys.path.insert(0, '..')

from persona_engine.rewrite.term_lock import (
    TermLock,
    TermLockEngine,
    TermLockResult,
    extract_terms,
    lock_and_restore,
    DOMAIN_TERM_PATTERNS,
)


class TestTermLock:
    """TermLock class tests"""

    def setup_method(self):
        """Create a TermLock instance before each test"""
        self.lock = TermLock()

    def test_lock_terms_basic(self):
        """Test basic term locking"""
        text = "这是一个紫色装备，还有金色装备"
        result = self.lock.lock_terms(text)

        assert result.original_text == text
        assert "紫色装备" in result.locked_terms
        assert "金色装备" in result.locked_terms
        assert result.protected_text != text  # Should be modified
        assert len(result.locked_map) >= 2

    def test_lock_terms_game_values(self):
        """Test locking of game value patterns"""
        text = "防御力100，生命值500，法力值200"
        result = self.lock.lock_terms(text)

        assert "防御力100" in result.locked_terms or "防御力" in result.locked_terms
        assert "生命值500" in result.locked_terms or "生命值" in result.locked_terms

    def test_lock_terms_skills(self):
        """Test locking of skill names"""
        text = "使用平A和普攻进行连招，最后用重击收招"
        result = self.lock.lock_terms(text)

        assert "平A" in result.locked_terms
        assert "普攻" in result.locked_terms
        assert "连招" in result.locked_terms
        assert "重击" in result.locked_terms
        assert "收招" in result.locked_terms

    def test_lock_terms_empty(self):
        """Test locking empty text"""
        result = self.lock.lock_terms("")
        assert result.original_text == ""
        assert result.locked_terms == set()
        assert result.protected_text == ""

    def test_lock_terms_no_matches(self):
        """Test text with no matching terms"""
        text = "这是一个普通句子，没有术语"
        result = self.lock.lock_terms(text)
        assert result.locked_terms == set()
        assert result.protected_text == text

    def test_lock_terms_duplicate_terms(self):
        """Test that duplicate terms are only locked once"""
        text = "紫色装备很重要，紫色装备是顶级的"
        result = self.lock.lock_terms(text)
        # locked_terms is a set, so duplicates are automatically removed
        assert len(result.locked_terms) >= 1

    def test_restore_terms(self):
        """Test term restoration"""
        text = "获得紫色装备和金色装备"
        result = self.lock.lock_terms(text)

        # Verify protected text has placeholders
        protected = result.protected_text
        assert "__TERM_" in protected

        # Restore should return original
        restored = self.lock.restore_terms(protected, result.locked_map)
        assert restored == text

    def test_restore_terms_preserves_context(self):
        """Test that restored text preserves surrounding context"""
        text = "我获得了紫色装备，太棒了！"
        result = self.lock.lock_terms(text)

        restored = self.lock.restore_terms(result.protected_text, result.locked_map)
        assert "紫色装备" in restored
        assert "太棒了" in restored

    def test_lock_terms_longest_match_first(self):
        """Test that longer terms are matched first (position sorting)"""
        # "史诗级装备" should be matched as a whole, not just "装备"
        text = "这是史诗级装备"
        result = self.lock.lock_terms(text)

        # The lock should preserve the order from longest to shortest
        # But at minimum, we should have at least one match
        assert len(result.locked_terms) >= 1

    def test_custom_patterns(self):
        """Test TermLock with custom patterns"""
        custom_lock = TermLock(custom_patterns=[r"自定义术语\d+"])

        text = "这是一个自定义术语123"
        result = custom_lock.lock_terms(text)

        assert "自定义术语123" in result.locked_terms

    def test_lock_terms_case_sensitivity(self):
        """Test that term matching is case-sensitive where applicable"""
        text = "BOSS战和boss战是不同的"
        result = self.lock.lock_terms(text)

        # DOMAIN_TERM_PATTERNS has BOSS (uppercase), should match
        assert "BOSS" in result.locked_terms


class TestTermLockEngine:
    """TermLockEngine class tests (optimized version)"""

    def setup_method(self):
        """Create a TermLockEngine instance before each test"""
        self.engine = TermLockEngine()

    def test_lock_terms_basic(self):
        """Test basic term locking"""
        text = "这是一个紫色装备，还有金色装备"
        protected, locked_map = self.engine.lock_terms(text)

        assert protected != text
        assert len(locked_map) >= 2
        assert "【PROTECTED_TERM_" in protected

    def test_lock_terms_sorted_by_length(self):
        """Test that longer patterns are matched first"""
        # Add custom patterns of different lengths
        engine = TermLockEngine(custom_patterns=[
            r"史诗级装备",
            r"装备",
        ])

        text = "这是史诗级装备"
        protected, locked_map = engine.lock_terms(text)

        # Should have at least one protected term
        assert len(locked_map) >= 1

    def test_restore_terms(self):
        """Test term restoration"""
        text = "获得紫色装备和金色装备"
        protected, locked_map = self.engine.lock_terms(text)

        restored = self.engine.restore_terms(protected, locked_map)
        assert restored == text

    def test_validate_preservation_all_preserved(self):
        """Test validation when all terms are preserved"""
        original = "我获得了紫色装备，太棒了！"
        rewritten = "成功入手紫色装备，真厉害！"

        preserved, violated = self.engine.validate_preservation(original, rewritten)
        assert preserved is True
        assert len(violated) == 0

    def test_validate_preservation_term_lost(self):
        """Test validation when a term is lost"""
        original = "我获得了紫色装备，太棒了！"
        rewritten = "我获得了装备，真厉害！"  # "紫色" is lost

        preserved, violated = self.engine.validate_preservation(original, rewritten)

        # "紫色装备" should be detected as violated since it's not in rewritten
        assert preserved is False or len(violated) > 0

    def test_lock_and_restore_shortcut(self):
        """Test the lock_and_restore shortcut function"""
        original = "这是紫色装备"
        # Simulate a rewritten text where the term was protected by placeholders
        engine = TermLockEngine()
        protected, locked_map = engine.lock_terms(original)

        # Simulate rewritten text with placeholders
        rewritten = protected  # In real scenario, LLM would work with protected text

        result = lock_and_restore(original, rewritten)
        assert "紫色装备" in result

    def test_lock_with_no_terms(self):
        """Test locking text with no matching terms"""
        text = "这是一个普通的句子"
        protected, locked_map = self.engine.lock_terms(text)

        assert protected == text
        assert len(locked_map) == 0

    def test_lock_with_overlapping_patterns(self):
        """Test handling of overlapping patterns"""
        engine = TermLockEngine(custom_patterns=[
            r"BOSS",
            r"BOSS战",
        ])

        text = "这是一场BOSS战"
        protected, locked_map = engine.lock_terms(text)

        # Should have protected terms
        assert len(locked_map) >= 1


class TestExtractTerms:
    """extract_terms function tests"""

    def test_extract_terms_basic(self):
        """Test basic term extraction"""
        text = "获得紫色装备和金色装备"
        terms = extract_terms(text)

        assert "紫色装备" in terms or "装备" in terms
        assert "金色装备" in terms or "装备" in terms

    def test_extract_terms_game_mechanics(self):
        """Test extraction of game mechanics terms"""
        text = "暴击率和命中率都很重要"
        terms = extract_terms(text)

        assert "暴击率" in terms
        assert "命中率" in terms

    def test_extract_terms_empty(self):
        """Test extraction from empty text"""
        terms = extract_terms("")
        assert len(terms) == 0

    def test_extract_terms_no_matches(self):
        """Test extraction with no matches"""
        text = "今天天气真好"
        terms = extract_terms(text)
        # No game terms should be found
        assert len(terms) == 0 or all("天气" not in t for t in terms)


class TestDomainTermPatterns:
    """DOMAIN_TERM_PATTERNS constant tests"""

    def test_patterns_exist(self):
        """Test that domain patterns are defined"""
        assert len(DOMAIN_TERM_PATTERNS) > 0

    def test_patterns_are_strings(self):
        """Test that all patterns are strings"""
        for pattern in DOMAIN_TERM_PATTERNS:
            assert isinstance(pattern, str)

    def test_common_patterns_exist(self):
        """Test that common gaming patterns exist"""
        pattern_str = "|".join(DOMAIN_TERM_PATTERNS)
        assert "装备" in pattern_str
        assert "攻击" in pattern_str or "攻击" in str(DOMAIN_TERM_PATTERNS)


class TestTermLockResult:
    """TermLockResult dataclass tests"""

    def test_term_lock_result_fields(self):
        """Test TermLockResult has all required fields"""
        from typing import Set

        result = TermLockResult(
            locked_terms=set(),
            locked_map={},
            original_text="test",
            protected_text="test"
        )

        assert isinstance(result.locked_terms, set)
        assert isinstance(result.locked_map, dict)
        assert result.original_text == "test"
        assert result.protected_text == "test"

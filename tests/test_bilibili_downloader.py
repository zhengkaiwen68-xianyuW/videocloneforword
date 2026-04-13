"""
Tests for bilibili_downloader.py 工具函数

覆盖：
- URL 验证函数
- 多 URL 解析函数
- UID 提取函数
"""
import pytest

import sys
sys.path.insert(0, '..')

from persona_engine.asr.bilibili_downloader import (
    is_valid_bilibili_url,
    parse_multiple_urls,
    is_valid_bilibili_space_url,
    extract_uid_from_space_url,
    build_video_url_from_bv,
)


class TestBilibiliUrlValidation:
    """B站视频 URL 验证测试"""

    def test_valid_bv_urls(self):
        """测试有效的 BV 号 URL"""
        valid_urls = [
            "https://www.bilibili.com/video/BV1xx411c7mD",
            "https://www.bilibili.com/video/BV1a4411c7L1",
            "http://www.bilibili.com/video/BV1234567890",
            "https://bilibili.com/video/BV1xx411c7mD",
        ]
        for url in valid_urls:
            assert is_valid_bilibili_url(url) is True, f"Should be valid: {url}"

    def test_valid_b23_urls(self):
        """测试有效的短 URL (b23.tv)"""
        valid_urls = [
            "https://b23.tv/abc123",
            "http://b23.tv/xyz789",
        ]
        for url in valid_urls:
            assert is_valid_bilibili_url(url) is True, f"Should be valid: {url}"

    def test_valid_bv_id_only(self):
        """测试纯 BV 号"""
        valid_ids = [
            "BV1xx411c7mD",
            "BV1234567890",
            "BV1a4411c7L1",
        ]
        for bv_id in valid_ids:
            assert is_valid_bilibili_url(bv_id) is True, f"Should be valid: {bv_id}"

    def test_invalid_urls(self):
        """测试无效 URL"""
        invalid_urls = [
            "https://youtube.com/video/abc",
            "https://www.bilibili.com/list/123",
            "https://space.bilibili.com/123456",
            "not a url",
            "",
            "   ",
        ]
        for url in invalid_urls:
            assert is_valid_bilibili_url(url) is False, f"Should be invalid: {url}"

    def test_url_with_whitespace(self):
        """测试带空白字符的 URL（应该被清理后验证）"""
        assert is_valid_bilibili_url("  https://www.bilibili.com/video/BV1xx411c7mD  ") is True


class TestParseMultipleUrls:
    """多行文本 URL 解析测试"""

    def test_single_url(self):
        """测试单行 URL"""
        text = "https://www.bilibili.com/video/BV1xx411c7mD"
        urls = parse_multiple_urls(text)
        assert len(urls) == 1
        assert urls[0] == "https://www.bilibili.com/video/BV1xx411c7mD"

    def test_multiple_urls(self):
        """测试多行 URL"""
        text = """
        https://www.bilibili.com/video/BV1xx411c7mD
        https://b23.tv/abc123
        https://www.bilibili.com/video/BV1234567890
        """
        urls = parse_multiple_urls(text)
        assert len(urls) == 3

    def test_mixed_valid_invalid(self):
        """测试混合有效和无效行"""
        text = """
        https://www.bilibili.com/video/BV1xx411c7mD
        invalid_url
        https://b23.tv/abc123
        not_a_bilibili_url
        """
        urls = parse_multiple_urls(text)
        assert len(urls) == 2

    def test_bv_id_completion(self):
        """测试纯 BV 号自动补全为 URL"""
        text = """
        BV1xx411c7mD
        BV1234567890
        """
        urls = parse_multiple_urls(text)
        assert len(urls) == 2
        assert urls[0] == "https://www.bilibili.com/video/BV1xx411c7mD"
        assert urls[1] == "https://www.bilibili.com/video/BV1234567890"

    def test_empty_text(self):
        """测试空文本"""
        assert parse_multiple_urls("") == []
        assert parse_multiple_urls("   \n   \n") == []

    def test_empty_lines_ignored(self):
        """测试空行被忽略"""
        text = "\n\nhttps://www.bilibili.com/video/BV1xx411c7mD\n\n\n"
        urls = parse_multiple_urls(text)
        assert len(urls) == 1


class TestSpaceUrlValidation:
    """B站个人空间 URL 验证测试"""

    def test_valid_space_urls(self):
        """测试有效的空间 URL"""
        valid_urls = [
            "https://space.bilibili.com/12345678",
            "http://space.bilibili.com/12345678/",
            "https://space.bilibili.com/12345678/video",
            "https://space.bilibili.com/1/video",
        ]
        for url in valid_urls:
            assert is_valid_bilibili_space_url(url) is True, f"Should be valid: {url}"

    def test_invalid_space_urls(self):
        """测试无效的空间 URL"""
        invalid_urls = [
            "https://www.bilibili.com/video/BV1xx411c7mD",
            "https://b23.tv/abc123",
            "https://space.bilibili.com/",  # 无 UID
            "not a url",
        ]
        for url in invalid_urls:
            assert is_valid_bilibili_space_url(url) is False, f"Should be invalid: {url}"


class TestExtractUidFromSpaceUrl:
    """从空间 URL 提取 UID 测试"""

    def test_extract_uid(self):
        """测试 UID 提取"""
        test_cases = [
            ("https://space.bilibili.com/12345678", "12345678"),
            ("http://space.bilibili.com/12345678/", "12345678"),
            ("https://space.bilibili.com/12345678/video", "12345678"),
            ("https://space.bilibili.com/1/video", "1"),
        ]
        for url, expected_uid in test_cases:
            assert extract_uid_from_space_url(url) == expected_uid, \
                f"URL: {url}, expected UID: {expected_uid}"

    def test_extract_uid_invalid(self):
        """测试无效 URL 返回 None"""
        invalid_urls = [
            "https://www.bilibili.com/video/BV1xx411c7mD",
            "https://space.bilibili.com/",  # 无 UID
            "not a url",
        ]
        for url in invalid_urls:
            assert extract_uid_from_space_url(url) is None, f"Should return None: {url}"

    def test_extract_uid_whitespace(self):
        """测试空白字符清理"""
        url = "  https://space.bilibili.com/12345678  "
        assert extract_uid_from_space_url(url) == "12345678"


class TestBuildVideoUrlFromBv:
    """从 BV 号构建 URL 测试"""

    def test_build_with_bv_prefix(self):
        """测试带 BV 前缀的 BV 号"""
        assert build_video_url_from_bv("BV1xx411c7mD") == \
            "https://www.bilibili.com/video/BV1xx411c7mD"

    def test_build_without_bv_prefix(self):
        """测试不带 BV 前缀的 BV 号"""
        assert build_video_url_from_bv("1xx411c7mD") == \
            "https://www.bilibili.com/video/BV1xx411c7mD"

    def test_build_with_whitespace(self):
        """测试空白字符清理"""
        assert build_video_url_from_bv("  BV1xx411c7mD  ") == \
            "https://www.bilibili.com/video/BV1xx411c7mD"

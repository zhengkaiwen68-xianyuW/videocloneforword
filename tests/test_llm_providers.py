"""
LLM Provider 抽象层单元测试

测试：
- LLMProvider Protocol 兼容性
- MiniMaxAdapter 初始化
- 工厂方法
- JSON 解析
"""

import pytest
from unittest.mock import patch, MagicMock

from persona_engine.llm.base import LLMProvider
from persona_engine.llm.factory import create_llm_provider
from persona_engine.llm.minimax import extract_json_with_stack, MiniMaxAdapter


# ── JSON 解析测试 ──

class TestExtractJsonWithStack:
    """JSON 栈解析测试"""

    def test_valid_json(self):
        """标准 JSON"""
        text = '{"key": "value", "num": 42}'
        result = extract_json_with_stack(text)
        assert result == {"key": "value", "num": 42}

    def test_nested_json(self):
        """嵌套 JSON"""
        text = '{"outer": {"inner": "value"}}'
        result = extract_json_with_stack(text)
        assert result == {"outer": {"inner": "value"}}

    def test_json_with_prefix(self):
        """带前缀文本的 JSON"""
        text = 'Here is the result:\n{"key": "value"}'
        result = extract_json_with_stack(text)
        assert result == {"key": "value"}

    def test_json_with_markdown(self):
        """带 markdown 代码块的 JSON"""
        text = '```json\n{"key": "value"}\n```'
        result = extract_json_with_stack(text)
        assert result == {"key": "value"}

    def test_invalid_json(self):
        """无效 JSON 应抛出异常"""
        with pytest.raises(ValueError):
            extract_json_with_stack("not json at all")

    def test_no_json_object(self):
        """无 JSON 对象应抛出异常"""
        with pytest.raises(ValueError, match="No JSON object found"):
            extract_json_with_stack("hello world")

    def test_unmatched_braces(self):
        """未匹配的花括号"""
        with pytest.raises(ValueError, match="unmatched braces"):
            extract_json_with_stack('{"key": "value"')

    def test_deeply_nested(self):
        """深层嵌套"""
        text = '{"a": {"b": {"c": {"d": "deep"}}}}'
        result = extract_json_with_stack(text)
        assert result["a"]["b"]["c"]["d"] == "deep"


# ── Protocol 兼容性测试 ──

class TestLLMProviderProtocol:
    """验证 MiniMaxAdapter 符合 LLMProvider Protocol"""

    def test_minimax_has_generate(self):
        """MiniMaxAdapter 有 generate 方法"""
        assert hasattr(MiniMaxAdapter, "generate")

    def test_minimax_has_generate_json(self):
        """MiniMaxAdapter 有 generate_json 方法"""
        assert hasattr(MiniMaxAdapter, "generate_json")


# ── 工厂方法测试 ──

class TestLLMFactory:
    """LLM 工厂方法测试"""

    @patch("persona_engine.llm.minimax.config")
    @patch("persona_engine.llm.factory.config")
    def test_create_minimax_provider(self, mock_factory_config, mock_minimax_config):
        """创建 MiniMax provider"""
        mock_factory_config.llm_provider = "minimax"
        mock_minimax_config.minimax = MagicMock()
        mock_minimax_config.minimax.api_key = "test_key"
        mock_minimax_config.minimax.base_url = "https://api.minimax.chat/v1"
        mock_minimax_config.minimax.model = "test-model"
        mock_minimax_config.minimax.timeout = 30

        provider = create_llm_provider("minimax")
        assert isinstance(provider, MiniMaxAdapter)

    def test_create_unsupported_provider(self):
        """不支持的 provider 应抛出异常"""
        with pytest.raises(ValueError, match="Unsupported"):
            create_llm_provider("unsupported_llm")


# ── MiniMax 初始化测试 ──

class TestMiniMaxInit:
    """MiniMax 适配器初始化测试"""

    @patch("persona_engine.llm.minimax.config")
    def test_init_with_defaults(self, mock_config):
        """使用默认配置初始化"""
        mock_config.minimax = MagicMock()
        mock_config.minimax.api_key = "test_key"
        mock_config.minimax.base_url = "https://api.minimax.chat/v1"
        mock_config.minimax.model = "MiniMax-M2.7"
        mock_config.minimax.timeout = 60

        adapter = MiniMaxAdapter()
        assert adapter.api_key == "test_key"
        assert adapter.model == "MiniMax-M2.7"

    @patch("persona_engine.llm.minimax.config")
    def test_init_with_custom_params(self, mock_config):
        """使用自定义参数初始化"""
        mock_config.minimax = MagicMock()
        mock_config.minimax.api_key = "default_key"
        mock_config.minimax.base_url = "https://api.minimax.chat/v1"
        mock_config.minimax.model = "default-model"
        mock_config.minimax.timeout = 60

        adapter = MiniMaxAdapter(api_key="custom_key", model="custom-model")
        assert adapter.api_key == "custom_key"
        assert adapter.model == "custom-model"

    @patch("persona_engine.llm.minimax.config")
    def test_init_no_api_key(self, mock_config):
        """无 API key 应抛出异常"""
        mock_config.minimax = MagicMock()
        mock_config.minimax.api_key = ""
        mock_config.minimax.base_url = "https://api.minimax.chat/v1"
        mock_config.minimax.model = "test"
        mock_config.minimax.timeout = 60

        with pytest.raises(ValueError, match="API key is required"):
            MiniMaxAdapter(api_key="")

"""
配置管理 - 短视频人格深度重构与洗稿引擎
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class MiniMaxConfig:
    """MiniMax API 配置"""
    api_key: str
    base_url: str = "https://api.minimax.chat/v1"
    model: str = "MiniMax-M2.7"
    timeout: int = 60  # 秒


@dataclass
class WhisperConfig:
    """Whisper ASR 配置"""
    model_size: str = "large-v3"
    language: str = "zh"
    device: str = "cuda"  # cuda 或 cpu
    compute_type: str = "float16"  # float16, float32, int8
    vad_filter: bool = True
    vad_parameters: dict[str, Any] = field(default_factory=lambda: {
        "min_silence_duration_ms": 500,
    })
    word_timestamps: bool = True


@dataclass
class DatabaseConfig:
    """数据库配置"""
    path: str = "persona_engine.db"
    echo: bool = False


@dataclass
class AuditConfig:
    """审计系统配置"""
    min_consistency_score: float = 90.0
    max_iterations: int = 5
    timeout_seconds: int = 300  # 5分钟
    # 评分权重
    verbal_tic_weight: float = 0.08
    grammar_weight: float = 0.20
    term_preservation_weight: float = 0.30
    rhythm_weight: float = 0.42


@dataclass
class AppConfig:
    """应用配置"""
    host: str = "127.0.0.1"
    port: int = 8080
    debug: bool = False
    # 数据目录
    data_dir: str = "data"
    # 监听文件夹
    watch_folder: str = "watch"


@dataclass
class BilibiliConfig:
    """
    B站下载配置

    参考BBDown设计: https://github.com/nilaoda/BBDown
    B站反爬机制:
    - 412: 请求被阻止，需要等待后重试
    - 429: 请求过于频繁
    - 403: 禁止访问，可能需要登录/Cookie

    优化策略:
    1. Cookie认证 - 提高请求稳定性
    2. 请求间隔可配置 - 避免高频触发限流
    3. 指数退避重试 - 失败后自动等待并重试
    4. 多API模式 - Web/TV/App/国际版切换
    """
    # 认证配置
    cookie: str = ""              # 网页Cookie (SESSDATA等)
    access_token: str = ""        # TV/App接口Token

    # 请求控制
    min_interval: float = 3.0     # 请求间隔最小值(秒)
    max_interval: float = 10.0    # 请求间隔最大值(秒)
    delay_per_page: float = 5.0   # 页面间延迟(秒)

    # 重试配置
    max_retries: int = 5          # 最大重试次数
    retry_base_delay: float = 2.0  # 指数退避基数(秒)

    # User-Agent
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    # API模式: web/tv/app/intl
    api_mode: str = "web"


class Config:
    """配置管理器"""

    _instance: "Config | None" = None
    _config: dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_config()
        return cls._instance

    def _load_config(self) -> None:
        """从 config.yaml 加载配置"""
        config_path = self._find_config_file()
        if config_path and config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                self._config = yaml.safe_load(f) or {}
        else:
            self._config = {}

    def _find_config_file(self) -> Path | None:
        """查找配置文件"""
        possible_paths = [
            Path("config.yaml"),
            Path("../config.yaml"),
            Path(__file__).parent.parent / "config.yaml",
            Path(__file__).parent.parent.parent / "config.yaml",
        ]
        for p in possible_paths:
            if p.exists():
                return p
        return None

    @property
    def minimax(self) -> MiniMaxConfig:
        """MiniMax API 配置"""
        cfg = self._config.get("minimax", {})
        api_key = cfg.get("api_key", os.getenv("MINIMAX_API_KEY", ""))
        if not api_key:
            raise ValueError("MiniMax API key not configured")
        return MiniMaxConfig(
            api_key=api_key,
            base_url=cfg.get("base_url", "https://api.minimax.chat/v1"),
            model=cfg.get("model", "MiniMax-M2.7"),
            timeout=cfg.get("timeout", 60),
        )

    @property
    def whisper(self) -> WhisperConfig:
        """Whisper ASR 配置"""
        cfg = self._config.get("whisper", {})
        return WhisperConfig(
            model_size=cfg.get("model_size", "large-v3"),
            language=cfg.get("language", "zh"),
            device=cfg.get("device", "cuda"),
            compute_type=cfg.get("compute_type", "float16"),
            vad_filter=cfg.get("vad_filter", True),
            vad_parameters=cfg.get("vad_parameters", {"min_silence_duration_ms": 500}),
            word_timestamps=cfg.get("word_timestamps", True),
        )

    @property
    def database(self) -> DatabaseConfig:
        """数据库配置"""
        cfg = self._config.get("database", {})
        return DatabaseConfig(
            path=cfg.get("path", "persona_engine.db"),
            echo=cfg.get("echo", False),
        )

    @property
    def audit(self) -> AuditConfig:
        """审计系统配置"""
        cfg = self._config.get("audit", {})
        return AuditConfig(
            min_consistency_score=cfg.get("min_consistency_score", 90.0),
            max_iterations=cfg.get("max_iterations", 5),
            timeout_seconds=cfg.get("timeout_seconds", 300),
            verbal_tic_weight=cfg.get("verbal_tic_weight", 0.25),
            grammar_weight=cfg.get("grammar_weight", 0.20),
            term_preservation_weight=cfg.get("term_preservation_weight", 0.30),
            rhythm_weight=cfg.get("rhythm_weight", 0.25),
        )

    @property
    def bilibili(self) -> BilibiliConfig:
        """
        B站下载配置

        参考BBDown设计: https://github.com/nilaoda/BBDown
        """
        cfg = self._config.get("bilibili", {})
        return BilibiliConfig(
            cookie=cfg.get("cookie", ""),
            access_token=cfg.get("access_token", ""),
            min_interval=cfg.get("min_interval", 3.0),
            max_interval=cfg.get("max_interval", 10.0),
            delay_per_page=cfg.get("delay_per_page", 5.0),
            max_retries=cfg.get("max_retries", 5),
            retry_base_delay=cfg.get("retry_base_delay", 2.0),
            user_agent=cfg.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
            api_mode=cfg.get("api_mode", "web"),
        )

    @property
    def app(self) -> AppConfig:
        """应用配置"""
        cfg = self._config.get("app", {})
        return AppConfig(
            host=cfg.get("host", "127.0.0.1"),
            port=cfg.get("port", 8080),
            debug=cfg.get("debug", False),
            data_dir=cfg.get("data_dir", "data"),
            watch_folder=cfg.get("watch_folder", "watch"),
        )

    def reload(self) -> None:
        """重新加载配置"""
        self._load_config()


# 全局配置实例
config = Config()

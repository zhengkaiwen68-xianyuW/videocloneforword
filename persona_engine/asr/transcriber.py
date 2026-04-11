"""
Faster-Whisper ASR 封装模块
支持 Silero VAD 优化配置，精确词级时间戳提取
"""

import os
from pathlib import Path
from typing import Iterator

from faster_whisper import WhisperModel

from ..core.config import config
from ..core.exceptions import (
    AudioFileNotFoundError,
    TranscriptionError,
    UnsupportedAudioFormatError,
)
from ..core.types import ASRResult, PauseInfo, WordTimestamp


# 支持的音频格式
SUPPORTED_FORMATS = {".mp3", ".mp4", ".wav", ".m4a", ".flac", ".ogg", ".webm"}


class WhisperTranscriber:
    """
    Faster-Whisper 语音转写器

    使用 Silero VAD 进行语音活动检测，获取精确的词级时间戳，
    支持计算语速(WPM)和停顿信息。
    """

    def __init__(
        self,
        model_size: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
    ):
        """
        初始化转写器

        Args:
            model_size: 模型大小 (tiny, base, small, medium, large-v3)
            device: 设备 (cuda, cpu)
            compute_type: 计算精度 (float16, float32, int8)
        """
        whisper_config = config.whisper

        self.model_size = model_size or whisper_config.model_size
        self.device = device or whisper_config.device
        self.compute_type = compute_type or whisper_config.compute_type
        self.language = whisper_config.language
        self.vad_filter = whisper_config.vad_filter
        self.vad_parameters = whisper_config.vad_parameters
        self.word_timestamps = whisper_config.word_timestamps

        # 延迟加载模型
        self._model: WhisperModel | None = None

    @property
    def model(self) -> WhisperModel:
        """懒加载模型"""
        if self._model is None:
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
        return self._model

    def _validate_file(self, file_path: str) -> None:
        """验证音频文件"""
        path = Path(file_path)
        if not path.exists():
            raise AudioFileNotFoundError(file_path)

        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_FORMATS:
            raise UnsupportedAudioFormatError(file_path, list(SUPPORTED_FORMATS))

    def transcribe(
        self,
        audio_path: str,
        language: str | None = None,
    ) -> ASRResult:
        """
        转写单个音频文件

        Args:
            audio_path: 音频文件路径
            language: 语言代码 (默认从配置读取)

        Returns:
            ASRResult: 包含文本、时间戳、WPM、停顿信息

        Raises:
            AudioFileNotFoundError: 文件不存在
            UnsupportedAudioFormatError: 不支持的格式
            TranscriptionError: 转写失败
        """
        self._validate_file(audio_path)

        try:
            lang = language or self.language

            # 执行转写 - 使用 Silero VAD 优化配置
            segments, info = self.model.transcribe(
                audio_path,
                language=lang,
                vad_filter=self.vad_filter,
                vad_parameters=self.vad_parameters,
                word_timestamps=self.word_timestamps,
            )

            # 收集词级时间戳
            words: list[WordTimestamp] = []
            full_text_parts: list[str] = []
            total_speech_duration = 0.0

            # 合并所有段落获取完整文本
            all_segments = list(segments)

            for segment in all_segments:
                if segment.text:
                    full_text_parts.append(segment.text.strip())

                # 提取词级时间戳
                if hasattr(segment, "words") and segment.words:
                    for word in segment.words:
                        words.append(
                            WordTimestamp(
                                word=word.word.strip(),
                                start=word.start,
                                end=word.end,
                            )
                        )
                        total_speech_duration += word.end - word.start

            full_text = " ".join(full_text_parts)

            # 获取总时长
            total_duration = info.duration or (words[-1].end if words else 0.0)

            # 计算 WPM (词/分钟)
            word_count = len(words)
            wpm = (word_count / total_speech_duration * 60) if total_speech_duration > 0 else 0.0

            # 分析停顿信息
            pauses = self._analyze_pauses(words)

            return ASRResult(
                file_path=audio_path,
                text=full_text,
                words=words,
                wpm=wpm,
                pauses=pauses,
                total_duration=total_duration,
                speech_duration=total_speech_duration,
                language=lang,
            )

        except AudioFileNotFoundError:
            raise
        except UnsupportedAudioFormatError:
            raise
        except Exception as e:
            raise TranscriptionError(
                message=f"Transcription failed: {str(e)}",
                file_path=audio_path,
                details={"error_type": type(e).__name__},
            )

    def transcribe_batch(
        self,
        audio_paths: list[str],
        language: str | None = None,
    ) -> Iterator[ASRResult]:
        """
        批量转写音频文件

        Args:
            audio_paths: 音频文件路径列表
            language: 语言代码

        Yields:
            ASRResult: 逐个返回转写结果
        """
        for path in audio_paths:
            try:
                result = self.transcribe(path, language)
                yield result
            except TranscriptionError:
                # 跳过失败的文件，继续处理下一个
                continue

    def _analyze_pauses(self, words: list[WordTimestamp]) -> list[PauseInfo]:
        """
        分析词间停顿信息

        MIN_PAUSE_THRESHOLD = 0.3s (PRD 要求捕捉有意义的气口)

        Args:
            words: 词级时间戳列表

        Returns:
            停顿信息列表
        """
        pauses: list[PauseInfo] = []

        for i in range(len(words) - 1):
            current_word = words[i]
            next_word = words[i + 1]

            # 计算当前词与下一词的间隙
            gap_duration = next_word.start - current_word.end

            # 只有超过阈值的停顿才被视为"人格气口"
            if gap_duration >= 0.3:
                pause_type = "LONG_PAUSE" if gap_duration > 0.8 else "NORMAL_PAUSE"
                pauses.append(
                    PauseInfo(
                        start=current_word.end,
                        end=next_word.start,
                        duration=round(gap_duration, 2),
                        after_word=current_word.word,
                        pause_type=pause_type,
                    )
                )

        return pauses

    def get_audio_info(self, audio_path: str) -> dict:
        """
        获取音频文件基本信息（不进行转写）

        Args:
            audio_path: 音频文件路径

        Returns:
            包含基本信息的字典
        """
        self._validate_file(audio_path)

        # 使用较短的音频段获取信息
        segments, info = self.model.transcribe(
            audio_path,
            language=self.language,
            vad_filter=self.vad_filter,
            vad_parameters=self.vad_parameters,
            word_timestamps=False,
            max_new_tokens=1,  # 只获取基本信息
        )

        # 消耗迭代器
        _ = list(segments)

        return {
            "duration": info.duration,
            "language": info.language,
            "language_probability": info.language_probability,
        }

    def release(self) -> None:
        """释放模型资源"""
        if self._model is not None:
            del self._model
            self._model = None

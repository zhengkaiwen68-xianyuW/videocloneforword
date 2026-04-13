"""
语音分析器 - 计算语速(WPM)和停顿特征
"""

from ..core.types import ASRResult, PauseInfo, TemporalPattern


class VoiceAnalyzer:
    """
    语音分析器

    从 ASR 结果中提取：
    - 语速 (WPM - Words Per Minute)
    - 停顿模式 (Pause patterns)
    - 时间序列特征 (Temporal patterns)
    """

    def __init__(self):
        pass

    def analyze(self, asr_result: ASRResult) -> TemporalPattern:
        """
        分析 ASR 结果，提取时间序列特征

        Args:
            asr_result: ASR 转写结果

        Returns:
            TemporalPattern: 时间序列特征
        """
        pauses = asr_result.pauses

        # 计算平均停顿时长
        avg_pause_duration = (
            sum(p.duration for p in pauses) / len(pauses) if pauses else 0.0
        )

        # 计算停顿频率 (次/分钟)
        speech_minutes = asr_result.speech_duration / 60
        pause_frequency = len(pauses) / speech_minutes if speech_minutes > 0 else 0.0

        # 确定节奏类型
        speech_rhythm = self._classify_rhythm(asr_result.wpm)

        # 生成兴奋度曲线
        excitement_curve = self._compute_excitement_curve(asr_result)

        return TemporalPattern(
            avg_pause_duration=avg_pause_duration,
            pause_frequency=pause_frequency,
            speech_rhythm=speech_rhythm,
            excitement_curve=excitement_curve,
        )

    def _classify_rhythm(self, wpm: float) -> str:
        """
        根据 WPM 分类节奏类型

        Args:
            wpm: 词/分钟

        Returns:
            节奏类型: fast/medium/slow
        """
        if wpm >= 180:
            return "fast"
        elif wpm >= 120:
            return "medium"
        else:
            return "slow"

    def _compute_excitement_curve(self, asr_result: ASRResult) -> list[float]:
        """
        计算兴奋度曲线

        通过分析语速变化和停顿模式来估算情绪波动。
        将语音分成多个段落，每段计算相对兴奋度。

        Args:
            asr_result: ASR 转写结果

        Returns:
            各段兴奋度值列表 (0.0 - 1.0)
        """
        words = asr_result.words
        if len(words) < 10:
            return [0.5]  # 数据不足，返回中等值

        # 将语音分成 5 个段落
        num_segments = 5
        segment_size = len(words) // num_segments
        excitement_curve = []

        for i in range(num_segments):
            start_idx = i * segment_size
            end_idx = start_idx + segment_size if i < num_segments - 1 else len(words)
            segment_words = words[start_idx:end_idx]

            # 计算该段的平均语速
            if len(segment_words) >= 2:
                segment_duration = segment_words[-1].end - segment_words[0].start
                segment_wpm = (len(segment_words) / segment_duration * 60) if segment_duration > 0 else 0

                # 计算该段的停顿密度
                # 用时间戳比较而非词索引计数，复杂度从 O(n²) 降至 O(n)，
                # 同时修正语速不均匀时停顿归属错判的逻辑 Bug
                seg_start_time = segment_words[0].start
                seg_end_time = segment_words[-1].end
                segment_pauses = [p for p in asr_result.pauses
                                 if seg_start_time <= p.start < seg_end_time]
                pause_density = len(segment_pauses) / segment_size if segment_size > 0 else 0

                # 兴奋度 = 归一化语速 * 0.7 + 反归一化停顿密度 * 0.3
                # 快语速 + 少停顿 = 高兴奋度
                normalized_wpm = min(segment_wpm / 200, 1.0)  # 200 WPM 为基准
                normalized_pause = max(0, 1 - pause_density * 2)  # 停顿越少越兴奋

                excitement = normalized_wpm * 0.7 + normalized_pause * 0.3
                excitement_curve.append(round(excitement, 3))
            else:
                excitement_curve.append(0.5)

        return excitement_curve

    def calculate_wpm(self, asr_result: ASRResult) -> float:
        """
        重新计算 WPM

        用于验证或修正 ASR 自带的 WPM 值。

        Args:
            asr_result: ASR 转写结果

        Returns:
            词/分钟
        """
        total_words = len(asr_result.words)
        speech_minutes = asr_result.speech_duration / 60

        if speech_minutes > 0:
            return round(total_words / speech_minutes, 2)
        return 0.0

    def get_pause_statistics(self, asr_result: ASRResult) -> dict:
        """
        获取停顿统计信息

        Args:
            asr_result: ASR 转写结果

        Returns:
            停顿统计数据
        """
        pauses = asr_result.pauses
        if not pauses:
            return {
                "total_pauses": 0,
                "avg_duration": 0.0,
                "max_duration": 0.0,
                "min_duration": 0.0,
                "long_pause_count": 0,
            }

        durations = [p.duration for p in pauses]
        long_pauses = [p for p in pauses if p.is_long_pause]

        return {
            "total_pauses": len(pauses),
            "avg_duration": round(sum(durations) / len(durations), 3),
            "max_duration": round(max(durations), 3),
            "min_duration": round(min(durations), 3),
            "long_pause_count": len(long_pauses),
            "long_pause_ratio": round(len(long_pauses) / len(pauses), 3),
        }

    def compare_rhythm(self, asr1: ASRResult, asr2: ASRResult) -> float:
        """
        比较两段语音的节奏相似度

        Args:
            asr1: 第一个 ASR 结果
            asr2: 第二个 ASR 结果

        Returns:
            相似度分数 (0.0 - 1.0)
        """
        # 语速差异
        wpm_diff = abs(asr1.wpm - asr2.wpm)
        wpm_similarity = max(0, 1 - wpm_diff / 100)

        # 停顿频率差异
        pause_freq_1 = len(asr1.pauses) / (asr1.speech_duration / 60) if asr1.speech_duration > 0 else 0
        pause_freq_2 = len(asr2.pauses) / (asr2.speech_duration / 60) if asr2.speech_duration > 0 else 0
        pause_diff = abs(pause_freq_1 - pause_freq_2)
        pause_similarity = max(0, 1 - pause_diff / 5)

        return round(wpm_similarity * 0.6 + pause_similarity * 0.4, 3)

    def convert_pauses_to_tags(
        self,
        words: list,
        wpm: float | None = None,
        short_pause_threshold: float = 0.3,
        long_pause_threshold: float = 0.8,
    ) -> str:
        """
        将 ASR 词级时间戳转换为带 [PAUSE] 标记的文本

        算法逻辑：
        1. 遍历 ASR 分词列表，计算相邻词汇间的时间间隙 (Gap)
        2. 根据预设阈值，将物理间隙映射为不同强度的 [PAUSE] 标记
        3. 产出带标记的原文，作为"人格特征"直接喂给重写引擎

        Args:
            words: ASR 词级时间戳列表 (WordTimestamp)
            wpm: 语速（用于联动调整阈值）
            short_pause_threshold: 短停顿阈值（默认 0.3s）
            long_pause_threshold: 长停顿阈值（默认 0.8s，与 PauseInfo.pause_type 一致）

        Returns:
            带 [PAUSE] 标记的文本字符串

        WPM 联动：
        - 如果 WPM > 200（快节奏），调低 short_pause_threshold 至 0.25s
        - 如果 WPM < 100（慢节奏），调高 short_pause_threshold 至 0.4s
        """
        # WPM 联动调整阈值
        if wpm is not None:
            if wpm > 200:
                # 快节奏：捕捉短促换气
                short_pause_threshold = 0.25
            elif wpm < 100:
                # 慢节奏：只捕捉明显停顿
                short_pause_threshold = 0.4

        tagged_segments = []

        for i in range(len(words)):
            # 添加当前词汇
            current_word = words[i].word.strip()
            tagged_segments.append(current_word)

            # 如果不是最后一个词，计算与下一词的间隙
            if i < len(words) - 1:
                gap = words[i + 1].start - words[i].end

                # 映射逻辑：对应"提取句后静音时长"
                if gap >= long_pause_threshold:
                    # 显著停顿：用于逻辑转折或悬念
                    tagged_segments.append(" [LONG_PAUSE] ")
                elif gap >= short_pause_threshold:
                    # 普通气口：用于自然换气或句间停顿
                    tagged_segments.append(" [PAUSE] ")

        return "".join(tagged_segments)

    def get_rhythm_text(self, asr_result: ASRResult) -> str:
        """
        获取带节奏标记的文本

        便捷方法：直接从 ASRResult 提取

        Args:
            asr_result: ASR 转写结果

        Returns:
            带 [PAUSE] 标记的文本
        """
        return self.convert_pauses_to_tags(
            words=asr_result.words,
            wpm=asr_result.wpm,
        )

"""
人格特征提取器 - 从 ASR 文本中提取作者人格画像

优化版：结合统计特征 + N-gram 自动发现 + AI 归纳
"""

import numpy as np
from collections import Counter
import json
import re

from ..core.exceptions import PersonalityExtractionError
from ..core.types import (
    DeepPsychology,
    LogicArchitecture,
    PersonalityProfile,
    TemporalPattern,
)


class PersonaInhibitor:
    """
    人格特征提取器（优化版）

    改进点：
    1. N-gram 自动发现口头禅，不局限于预设列表
    2. 统计特征：WPM、Gap、句长方差
    3. AI 辅助归纳人格画像
    """

    def __init__(self, llm_adapter=None, tic_threshold: int = 3):
        """
        初始化提取器

        Args:
            llm_adapter: LLM 适配器（用于 AI 辅助提取）
            tic_threshold: 口头禅频率阈值（默认 >= 3 次）
        """
        self.llm = llm_adapter
        self.tic_threshold = tic_threshold

    def _extract_statistical_features(self, asr_data_list: list[dict]) -> dict:
        """
        步骤 1: 物理特征提取 (WPM, Gap, 句长)

        Args:
            asr_data_list: ASR 数据列表，每项包含:
                - text: 转写文本
                - words_objects: Faster-Whisper 原始词对象列表
                - duration: 音频时长（秒）

        Returns:
            统计特征字典
        """
        all_sentences = []
        pauses = []
        total_word_count = 0
        total_duration = 0

        for data in asr_data_list:
            # 使用原始词对象（dataclass 对象，有 .start / .end 属性）
            words = data.get('words_objects', [])
            total_word_count += len(words)
            total_duration += data.get('duration', 0)

            # 句长计算（多标点分割）
            text = data.get('text', '')
            current_sentences = re.split(r'[。！？；]', text)
            all_sentences.extend([len(s) for s in current_sentences if len(s) > 1])

            # Gap 计算（停顿 > 0.3s 认定为刻意停顿）
            for i in range(len(words) - 1):
                gap = words[i + 1].start - words[i].end
                if gap > 0.3:
                    pauses.append(gap)

        # 句长方差
        sentence_var = float(np.var(all_sentences)) if all_sentences else 0.0

        # 全局 WPM
        avg_wpm = (total_word_count / total_duration * 60) if total_duration > 0 else 0

        stats = {
            "avg_wpm": round(avg_wpm, 1),
            "sentence_var": round(sentence_var, 2),
            "pause_density": len(pauses) / len(asr_data_list) if asr_data_list else 0,
            "top_n_grams": self._get_refined_ngrams(asr_data_list),
            "total_words": total_word_count,
            "total_pauses": len(pauses),
        }
        return stats

    def _get_refined_ngrams(self, data_list: list[dict]) -> list[str]:
        """
        利用 N-gram 自动发现作者特有的词组

        改进：不局限于预设列表，通过统计高频 2-4 字词组自动发现口头禅

        Args:
            data_list: ASR 数据列表

        Returns:
            高频词组列表（已过滤停用词）
        """
        full_text = "".join([d.get('text', '') for d in data_list])
        # 匹配 2-4 字的中文字符串
        candidates = re.findall(r'[\u4e00-\u9fa5]{2,4}', full_text)
        counts = Counter(candidates)

        # 停用词过滤
        stop_words = {
            "的是", "的一", "是这个", "那个的", "是这样",
            "测试", "这个", "什么", "可以", "就是", "然后",
            "所以", "但是", "因为", "所以说", "有的",
        }

        refined = [
            word for word, freq in counts.most_common(15)
            if freq >= self.tic_threshold and word not in stop_words
        ]
        return refined[:10]

    def generate_persona_report(self, asr_data_list: list[dict]) -> dict:
        """
        步骤 2: AI 特征压缩与归纳

        Args:
            asr_data_list: ASR 数据列表

        Returns:
            《人格属性清单》字典
        """
        # 1. 硬核统计
        raw_stats = self._extract_statistical_features(asr_data_list)

        # 2. 采样前3篇作为示例
        sample_texts = [d.get('text', '') for d in asr_data_list[:3]]
        full_text_sample = "\n---\n".join(sample_texts)

        # 3. 构建 Prompt
        prompt = f"""你是一位深度语言学专家。请分析以下3篇短视频转写文本及统计数据：

统计数据：
- 语速：{raw_stats['avg_wpm']} WPM
- 句长波动系数：{raw_stats['sentence_var']}
- 平均气口数：{raw_stats['pause_density']:.1f}
- 高频词组：{raw_stats['top_n_grams']}

样本文本：
{full_text_sample}

请输出一份《人格属性清单》JSON，必须包含：
{{
    "verbal_tics": ["核心口头禅列表，按频率排序"],
    "grammar_prefs": ["语法偏好列表，如：短句偏好、善用连接词"],
    "logic_architecture": {{
        "opening_style": "开场风格，如：开门见山",
        "transition_patterns": ["过渡模式列表"],
        "closing_style": "结尾风格，如：总结收尾",
        "topic_organization": "话题组织方式，如：线性叙述"
    }},
    "temporal_patterns": {{
        "speech_rhythm": "语速节奏：fast/medium/slow",
        "pause_frequency": "停顿频率",
        "excitement_curve": [0.5, 0.6, 0.7, 0.6, 0.5]
    }},
    "emotion_tone": "情绪色调描述",
    "deep_psychology": {{
        "emotional_tone": "情绪基调，如：{{亢奋激动}}/{{毒舌吐槽}}/{{温情脉脉}}/{{平稳中立}}",
        "emotional_arc": ["情绪曲线，如：引入、爆发、回落"],
        "rhetorical_devices": ["修辞手法，如：反问句、感叹句、排比"],
        "lexicon": ["专属实词，如：猛、牛、绝杀、神装"]
    }}
}}"""

        # 4. 调用 LLM 获取画像
        if self.llm:
            persona_json = self.llm.generate_json(prompt=prompt)
        else:
            # 无 LLM 时返回统计结果
            persona_json = {
                "verbal_tics": raw_stats['top_n_grams'],
                "grammar_prefs": [],
                "logic_architecture": {},
                "temporal_patterns": {
                    "speech_rhythm": "medium",
                    "pause_frequency": raw_stats['pause_density'],
                    "excitement_curve": [0.5, 0.6, 0.7, 0.6, 0.5],
                },
                "emotion_tone": "待分析",
                "deep_psychology": {
                    "emotional_tone": "待分析",
                    "emotional_arc": ["引入", "展开", "收尾"],
                    "rhetorical_devices": [],
                    "lexicon": raw_stats['top_n_grams'][:5],
                },
            }

        return persona_json


# ========== 兼容旧接口的 PersonalityExtractor ==========

class PersonalityExtractor:
    """
    人格特征提取器（兼容旧接口）

    输入多篇 ASR 文本，调用 AI 归纳人格特征：
    - 口头禅
    - 语法偏好
    - 逻辑架构
    - 时间序列特征
    """

    # 候选口头禅模式 (常见语气词)
    VERBAL_TIC_PATTERNS = [
        r"那个", r"然后", r"其实", r"就是说", r"好吧",
        r"嗯", r"啊", r"呢", r"我觉得", r"应该",
        r"可能", r"大概", r"反正", r"所以", r"但是",
        r"不过", r"而且", r"然后呢", r"不是", r"对",
        r"没错", r"这个", r"什么", r"怎么说", r"你知道",
    ]

    def __init__(self, llm_adapter=None):
        self.llm_adapter = llm_adapter

    def extract(self, texts: list[str], author_name: str) -> PersonalityProfile:
        """
        从多篇文本中提取人格特征

        Args:
            texts: ASR 原文列表
            author_name: 作者名称

        Returns:
            PersonalityProfile: 人格画像
        """
        if len(texts) < 1:
            raise PersonalityExtractionError(
                message="At least 1 text required for personality extraction",
                texts_count=len(texts),
            )

        # 使用优化版的 PersonaInhibitor
        inhibitor = PersonaInhibitor(llm_adapter=self.llm_adapter)

        # 转换为兼容格式
        asr_data_list = [
            {"text": text, "words_objects": [], "duration": 0}
            for text in texts
        ]

        # 生成画像
        persona_dict = inhibitor.generate_persona_report(asr_data_list)

        import uuid
        persona_id = str(uuid.uuid4())[:8]

        return PersonalityProfile(
            id=persona_id,
            name=author_name,
            verbal_tics=persona_dict.get("verbal_tics", []),
            grammar_prefs=persona_dict.get("grammar_prefs", []),
            logic_architecture=LogicArchitecture(
                opening_style=persona_dict.get("logic_architecture", {}).get("opening_style", "开门见山"),
                transition_patterns=persona_dict.get("logic_architecture", {}).get("transition_patterns", []),
                closing_style=persona_dict.get("logic_architecture", {}).get("closing_style", "总结收尾"),
                topic_organization=persona_dict.get("logic_architecture", {}).get("topic_organization", "线性叙述"),
            ),
            temporal_patterns=TemporalPattern(
                avg_pause_duration=0.5,
                pause_frequency=persona_dict.get("temporal_patterns", {}).get("pause_frequency", 1.5),
                speech_rhythm=persona_dict.get("temporal_patterns", {}).get("speech_rhythm", "medium"),
                excitement_curve=persona_dict.get("temporal_patterns", {}).get("excitement_curve", [0.5, 0.6, 0.7, 0.6, 0.5]),
            ),
            deep_psychology=DeepPsychology(
                emotional_tone=persona_dict.get("deep_psychology", {}).get("emotional_tone", "平稳中立"),
                emotional_arc=persona_dict.get("deep_psychology", {}).get("emotional_arc", ["引入", "展开", "收尾"]),
                rhetorical_devices=persona_dict.get("deep_psychology", {}).get("rhetorical_devices", []),
                lexicon=persona_dict.get("deep_psychology", {}).get("lexicon", persona_dict.get("verbal_tics", [])[:5]),
            ),
            raw_json=persona_dict,
            source_asr_texts=texts,
        )

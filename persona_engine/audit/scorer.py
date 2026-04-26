"""
一致性评分器

计算重写文案与原始人格画像的一致性得分

改进点：
1. 术语保护设为"硬熔断机制" - preservation_rate < 1.0 直接触发重写
2. 引入"停顿位置合理性"检查
3. 调用反向推导 Agent 进行 AI 辅助评分
"""

import re
import logging
from typing import Any

from ..core.config import config
from ..core.types import HookAnalysis, HookType, PersonalityProfile, TopicTechnique
from ..core.exceptions import ConsistencyScoreError
from .reverse_agent import ReverseAgent


logger = logging.getLogger(__name__)

# 语法断句点模式（用于检查停顿位置合理性）
BREAKPOINT_PATTERNS = [
    r'[，,]',
    r'[。]',
    r'[！？]',
    r'[；]',
    r'(然后|所以|但是|不过|而且|如果|因为)',
]


class ConsistencyScorer:
    """
    一致性评分器

    改进后的评分维度：
    1. 术语硬熔断 - 变动率必须为 0
    2. 口头禅命中 (25%)
    3. 语法偏好 (20%)
    4. 节奏契合 (25%) - 含位置合理性检查

    通过阈值：>= 90 分
    """

    def __init__(self, reverse_agent: ReverseAgent):
        """
        初始化评分器

        Args:
            reverse_agent: 反向推导 Agent（用于 AI 辅助评分）
        """
        self.reverse_agent = reverse_agent
        self.audit_config = config.audit

        # 评分权重
        self.weights = {
            "verbal_tic": self.audit_config.verbal_tic_weight,
            "grammar": self.audit_config.grammar_weight,
            "term_preservation": self.audit_config.term_preservation_weight,
            "rhythm": self.audit_config.rhythm_weight,
        }

    async def score(
        self,
        rewritten_text: str,
        original_profile: PersonalityProfile,
        locked_terms: list[str],
    ) -> dict[str, Any]:
        """
        计算一致性评分

        Args:
            rewritten_text: 重写后的文案
            original_profile: 原始人格画像
            locked_terms: 需要保护的术语列表

        Returns:
            {
                "total_score": 87.5,
                "status": "SUCCESS" | "FAIL_TERM_PROTECTION" | "FAIL_MAX_ITERATIONS",
                "verbal_tic_score": 90.0,
                "grammar_score": 85.0,
                "rhythm_score": 75.0,
                "passed": False,
                "details": {...}
            }
        """
        try:
            # ========== 1. 术语硬约束检查 ==========
            missing_terms = [t for t in locked_terms if t not in rewritten_text]
            if missing_terms:
                logger.warning(f"Term protection failed: missing {missing_terms}")
                return {
                    "total_score": 0,
                    "status": "FAIL_TERM_PROTECTION",
                    "reason": f"术语丢失: {missing_terms}",
                    "passed": False,
                    "details": {"missing_terms": missing_terms},
                }

            # ========== 2. 调用审计 Agent 反向推导 ==========
            try:
                derived_features = await self.reverse_agent.reverse_extract(rewritten_text)
            except Exception as e:
                logger.warning(f"Reverse extraction failed: {e}, using rule-based scoring")
                derived_features = {}

            # ========== 3. 维度加权计算 ==========
            verbal_tic_score = self._score_verbal_tics(rewritten_text, original_profile)
            grammar_score = self._score_grammar(rewritten_text, original_profile)
            term_preservation_score = self._score_term_preservation(rewritten_text, locked_terms)
            rhythm_score = self._score_rhythm(rewritten_text, original_profile)

            # 加权综合
            total_score = (
                verbal_tic_score * self.weights["verbal_tic"]
                + grammar_score * self.weights["grammar"]
                + term_preservation_score * self.weights["term_preservation"]
                + rhythm_score * self.weights["rhythm"]
            )

            # 通过阈值
            min_score = self.audit_config.min_consistency_score

            return {
                "total_score": round(total_score, 2),
                "status": "SUCCESS",
                "verbal_tic_score": round(verbal_tic_score, 2),
                "grammar_score": round(grammar_score, 2),
                "term_preservation_score": round(term_preservation_score, 2),
                "rhythm_score": round(rhythm_score, 2),
                "passed": total_score >= min_score,
                "min_required": min_score,
                "derived_features": derived_features,
                "details": {
                    "verbal_tic_details": self._get_verbal_tic_details(
                        rewritten_text, original_profile
                    ),
                    "grammar_details": self._get_grammar_details(
                        rewritten_text, original_profile
                    ),
                    "rhythm_details": self._get_rhythm_details(
                        rewritten_text, original_profile
                    ),
                },
            }

        except Exception as e:
            raise ConsistencyScoreError(
                message=f"Scoring failed: {str(e)}",
                details={"error_type": type(e).__name__},
            )

    def _score_verbal_tics(
        self,
        text: str,
        profile: PersonalityProfile,
    ) -> float:
        """口头禅评分"""
        if not profile.verbal_tics:
            return 50.0

        original_tics = set(profile.verbal_tics)
        text_lower = text.lower()

        found_count = sum(1 for tic in original_tics if tic.lower() in text_lower)
        hit_rate = found_count / len(original_tics) if original_tics else 0

        if hit_rate >= 0.7:
            return 100.0
        elif hit_rate >= 0.5:
            return 80.0
        elif hit_rate >= 0.3:
            return 60.0
        else:
            return max(40.0, hit_rate * 100)

    def _score_grammar(
        self,
        text: str,
        profile: PersonalityProfile,
    ) -> float:
        """语法偏好评分"""
        if not profile.grammar_prefs:
            return 70.0

        sentences = re.split(r"[。！？。！？\n]", text)
        sentences = [s.strip() for s in sentences if s.strip()]

        if not sentences:
            return 50.0

        avg_len = sum(len(s) for s in sentences) / len(sentences)

        scores = []
        for pref in profile.grammar_prefs:
            if "长句" in pref and avg_len > 25:
                scores.append(100)
            elif "短句" in pref and avg_len < 20:
                scores.append(100)
            elif "长句" in pref or "短句" in pref:
                scores.append(60)
            else:
                scores.append(70)

        return sum(scores) / len(scores) if scores else 70.0

    def _score_term_preservation(self, text: str, locked_terms: list[str]) -> float:
        """
        术语保护评分

        评估所有锁定术语是否在重写文本中保持原样
        """
        if not locked_terms:
            return 100.0

        missing_terms = [t for t in locked_terms if t not in text]
        preservation_rate = (len(locked_terms) - len(missing_terms)) / len(locked_terms)

        if preservation_rate == 1.0:
            return 100.0
        elif preservation_rate >= 0.9:
            return 80.0
        elif preservation_rate >= 0.7:
            return 60.0
        elif preservation_rate >= 0.5:
            return 40.0
        else:
            return 0.0

    def _score_rhythm(
        self,
        text: str,
        profile: PersonalityProfile,
    ) -> float:
        """
        节奏契合评分（改进版）

        评估：
        1. PAUSE 标记密度（每句话的停顿次数）
        2. 停顿位置合理性（是否在语法断句点）
        """
        pause_markers = re.findall(r"\[PAUSE\]", text)
        pause_count = len(pause_markers)

        # 如果没有停顿标记，得分很低
        if pause_count == 0:
            return 30.0

        # 按句子分段计算停顿密度
        # 句子分割：按句号、逗号、问号、感叹号分割
        sentences = re.split(r'[。！？，、]', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        sentence_count = max(len(sentences), 1)

        # 计算每句话的平均停顿次数
        pauses_per_sentence = pause_count / sentence_count

        original_rhythm = profile.temporal_patterns.speech_rhythm

        # 根据目标节奏设定每句话的目标停顿次数
        if original_rhythm == "fast":
            target_pauses_per_sentence = 0.3  # 快节奏：约每3句话1次停顿
        elif original_rhythm == "slow":
            target_pauses_per_sentence = 1.5  # 慢节奏：约每句话1-2次停顿
        else:
            target_pauses_per_sentence = 0.8  # 中等节奏：约每1-2句话1次停顿

        # 计算偏差
        diff = abs(pauses_per_sentence - target_pauses_per_sentence)

        # 密度得分：偏差越小得分越高
        if diff < 0.2:
            density_score = 100.0
        elif diff < 0.4:
            density_score = 85.0
        elif diff < 0.6:
            density_score = 70.0
        elif diff < 1.0:
            density_score = 55.0
        else:
            density_score = max(40.0, 100 - diff * 30)

        # ========== 停顿位置合理性检查 ==========
        position_score = self._score_pause_position(text, pause_markers)

        # 综合得分 = 密度得分 * 0.7 + 位置得分 * 0.3
        return density_score * 0.7 + position_score * 0.3

    def _score_pause_position(self, text: str, pause_markers: list[str]) -> float:
        """
        评估停顿位置合理性

        检查 [PAUSE] 是否出现在语法断句点（连接词、逗号、句号后）

        Args:
            text: 重写文案
            pause_markers: [PAUSE] 标记列表

        Returns:
            位置合理性得分 (0-100)
        """
        if not pause_markers:
            return 50.0  # 无标记，默认中等

        # 查找所有断句点位置
        breakpoint_positions = set()
        for pattern in BREAKPOINT_PATTERNS:
            for match in re.finditer(pattern, text):
                breakpoint_positions.add(match.start())

        # 统计 [PAUSE] 出现在断句点后的情况
        reasonable_count = 0
        for marker_match in re.finditer(r'\[PAUSE\]', text):
            marker_pos = marker_match.start()
            # 检查前方 10 个字符内是否有断句点
            search_start = max(0, marker_pos - 10)
            context = text[search_start:marker_pos]
            if any(bp in breakpoint_positions for bp in range(search_start, marker_pos)):
                reasonable_count += 1

        position_rate = reasonable_count / len(pause_markers)

        if position_rate >= 0.8:
            return 100.0
        elif position_rate >= 0.6:
            return 80.0
        elif position_rate >= 0.4:
            return 60.0
        else:
            return max(40.0, position_rate * 100)

    def _get_verbal_tic_details(
        self,
        text: str,
        profile: PersonalityProfile,
    ) -> dict[str, Any]:
        """获取口头禅评分详情"""
        original_tics = set(profile.verbal_tics)
        text_lower = text.lower()

        found = [tic for tic in original_tics if tic.lower() in text_lower]
        missing = [tic for tic in original_tics if tic.lower() not in text_lower]

        return {
            "original_count": len(original_tics),
            "found_count": len(found),
            "found": found,
            "missing": missing,
        }

    def _get_grammar_details(
        self,
        text: str,
        profile: PersonalityProfile,
    ) -> dict[str, Any]:
        """获取语法评分详情"""
        sentences = re.split(r"[。！？。！？\n]", text)
        sentences = [s.strip() for s in sentences if s.strip()]

        avg_len = sum(len(s) for s in sentences) / len(sentences) if sentences else 0

        return {
            "sentence_count": len(sentences),
            "avg_sentence_length": round(avg_len, 1),
            "preferences": profile.grammar_prefs,
        }

    def _get_rhythm_details(
        self,
        text: str,
        profile: PersonalityProfile,
    ) -> dict[str, Any]:
        """获取节奏评分详情"""
        pause_markers = re.findall(r"\[PAUSE\]", text)
        text_length = len(text)
        density = (len(pause_markers) / text_length * 100) if text_length > 0 else 0

        return {
            "pause_count": len(pause_markers),
            "pause_density": round(density, 2),
            "original_rhythm": profile.temporal_patterns.speech_rhythm,
            "original_pause_freq": profile.temporal_patterns.pause_frequency,
        }

    def _score_hook_technique(
        self,
        hook_text: str,
        target_technique: HookAnalysis,
    ) -> dict[str, Any]:
        """
        评估重写文案的钩子是否使用了目标技法

        评分维度：
        1. 技法类型匹配度
        2. 结构公式一致性
        3. 心理机制是否触发

        Args:
            hook_text: 待评估的钩子文案
            target_technique: 目标钩子技法

        Returns:
            {"score": float, "details": dict}
        """
        if not target_technique or not hook_text:
            return {"score": 100.0, "details": {"reason": "无目标技法，默认通过"}}

        scores = []
        details = {}

        # 1. 技法类型匹配（简单关键词检测）
        type_score = self._check_hook_type_match(hook_text, target_technique.hook_type)
        scores.append(type_score)
        details["type_match"] = type_score

        # 2. 结构公式一致性（检查是否包含公式中的关键词）
        formula = target_technique.structural_formula
        if formula:
            # 提取公式中的非变量部分
            formula_keywords = [
                w for w in formula.replace("{", "").replace("}", "").split()
                if len(w) >= 2 and w not in {"的", "了", "是", "在", "和"}
            ]
            if formula_keywords:
                matched = sum(1 for kw in formula_keywords if kw in hook_text)
                formula_score = min(100.0, matched / len(formula_keywords) * 100)
            else:
                formula_score = 80.0
            scores.append(formula_score)
            details["formula_match"] = formula_score

        total = sum(scores) / len(scores) if scores else 100.0
        return {"score": round(total, 2), "details": details}

    def _score_topic_alignment(
        self,
        hook_text: str,
        topic_technique: TopicTechnique,
    ) -> dict[str, Any]:
        """
        评估钩子的选题切入角度是否符合目标技法

        Args:
            hook_text: 待评估的钩子文案
            topic_technique: 目标选题技法

        Returns:
            {"score": float, "details": dict}
        """
        if not topic_technique or not hook_text:
            return {"score": 100.0, "details": {"reason": "无目标选题技法，默认通过"}}

        hook_lower = hook_text.lower()

        # 检查痛点匹配
        pain_hits = 0
        for pain in topic_technique.pain_points:
            if pain.lower() in hook_lower:
                pain_hits += 1

        # 检查角度匹配
        angle_hits = 0
        for angle in topic_technique.angle_patterns:
            angle_keywords = angle.replace("/", " ").replace("、", " ").split()
            if any(kw.lower() in hook_lower for kw in angle_keywords):
                angle_hits += 1

        pain_score = min(100.0, pain_hits * 50) if topic_technique.pain_points else 80.0
        angle_score = min(100.0, angle_hits * 50) if topic_technique.angle_patterns else 80.0

        total = pain_score * 0.5 + angle_score * 0.5
        return {"score": round(total, 2), "details": {"pain_hits": pain_hits, "angle_hits": angle_hits}}

    @staticmethod
    def _check_hook_type_match(hook_text: str, target_type: HookType) -> float:
        """检查钩子是否符合目标类型（规则检测）"""
        text = hook_text.strip()

        type_indicators = {
            HookType.REVERSE_LOGIC: ["不是", "根本", "其实", "从来没", "别再"],
            HookType.PAIN_POINT: ["还在", "你是不是", "有没有", "是不是也"],
            HookType.BENEFIT_BOMB: ["秒", "分钟", "一步", "只需", "搞定"],
            HookType.SUSPENSE_CUTOFF: ["因为", "但是", "后来", "结果"],
            HookType.AUTHORITY_SUBVERT: ["专家", "教授", "巴菲特", "大佬"],
            HookType.DATA_IMPACT: ["%", "万", "亿", "倍", "差距"],
            HookType.IDENTITY_LABEL: ["如果你也", "你是", "这类人", "像你这样"],
        }

        indicators = type_indicators.get(target_type, [])
        if not indicators:
            return 80.0

        matches = sum(1 for ind in indicators if ind in text)
        if matches >= 1:
            return 100.0
        return 50.0  # 无法确认但也不一定错

    def _score_golden_hook(self, text: str) -> dict[str, Any]:
        """
        黄金开场专项检测（一票否决制）

        评估开场文案是否符合"黄金3秒"原则：
        1. AI 味黑名单检测
        2. 开场长度检测

        Returns:
            {
                "score": 100.0 (合格) | 50.0 (警告) | 0.0 (不合格),
                "reason": "检测说明"
            }
        """
        if not text:
            return {"score": 0.0, "reason": "文本为空"}

        # 提取前 30 个字符作为开场分析区
        opening = text[:30]

        # AI 味与废话黑名单校验
        ai_smell_blacklist = [
            "今天我们", "众所周知", "你知道吗", "敢相信",
            "探讨一下", "随着社会", "在这个时代", "大家好",
            "首先", "然后", "接下来", "也就是说",
        ]
        for word in ai_smell_blacklist:
            if word in opening:
                return {"score": 0.0, "reason": f"触发AI味黑名单: 包含『{word}』"}

        # 结构校验：单句过长无法形成短视频需要的视觉冲击力
        first_clause = opening.split('，')[0] if '，' in opening else opening
        first_clause = first_clause.split('。')[0] if '。' in first_clause else first_clause

        if len(first_clause) > 20:
            return {"score": 50.0, "reason": f"开场单句过长（{len(first_clause)}字），节奏拖沓，无法形成有效冲击力"}

        return {"score": 100.0, "reason": "未检测到明显违规"}

    async def _score_semantic_vibe(
        self,
        rewritten_text: str,
        original_profile: PersonalityProfile,
    ) -> dict[str, Any]:
        """
        【LLM-as-a-Judge】评估正文语义神似度

        使用大模型评估重写文案与目标人格的"神似度"，
        摆脱死板的字数统计，转向语义层面的质量评估。

        Args:
            rewritten_text: 候选重写正文
            original_profile: 目标人格画像

        Returns:
            {
                "score": float,  # 0-100 的神似度评分
                "reason": str    # 具体点评
            }
        """
        if getattr(self, 'reverse_agent', None) is None:
            logger.warning("ReverseAgent 未配置，默认语义评分为 80 分")
            return {"score": 80.0, "reason": "未配置评委模型，默认通过"}

        psy = original_profile.deep_psychology
        prompt = f"""作为短视频编导，请给这段重写文案的"神似度"打分(0-100)。

评估标准：
1. 情绪基调是否符合：{psy.emotional_tone}
2. 是否自然使用了专属词汇：{', '.join(psy.lexicon[:5]) if psy.lexicon else '无'}
3. 语感与修辞是否到位：{', '.join(psy.rhetorical_devices) if psy.rhetorical_devices else '无'}

待评文案：{rewritten_text}

返回严格JSON格式：
{{"score": 85, "reason": "具体点评，指出哪里不像或者缺了什么味道"}}
"""
        try:
            # 借用模型适配器进行格式化输出
            res = await self.reverse_agent.model_adapter.generate_json(
                prompt=prompt,
                system_prompt="你是严厉的文风审计官"
            )
            return {
                "score": float(res.get("score", 70.0)),
                "reason": res.get("reason", "")
            }
        except Exception as e:
            logger.error(f"Vibe scoring failed: {e}")
            return {"score": 75.0, "reason": "评分API异常"}

    def quick_score(
        self,
        rewritten_text: str,
        original_profile: PersonalityProfile,
        locked_terms: list[str],
    ) -> float:
        """
        快速评分（不调用 AI）

        用于初步筛选
        """
        # 术语硬检查
        missing_terms = [t for t in locked_terms if t not in rewritten_text]
        if missing_terms:
            return 0.0

        # 简单加权
        verbal_tic_score = self._score_verbal_tics(rewritten_text, original_profile)
        rhythm_score = self._score_rhythm(rewritten_text, original_profile)

        return verbal_tic_score * 0.5 + rhythm_score * 0.5

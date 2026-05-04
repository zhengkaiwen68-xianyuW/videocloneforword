"""
人格注入引擎

将人格特征注入到重写 Prompt 中，控制 LLM 的输出风格
"""

import json
import re
import logging
from typing import Any

logger = logging.getLogger(__name__)

from ..core.types import (
    ContentStructureMap,
    HookAnalysis,
    PersonalityProfile,
    TopicTechnique,
)
from ..core.exceptions import PersonaInjectionError
from ..llm.minimax import MiniMaxAdapter
from .term_lock import TermLock, TermLockResult


def _get_rag_retriever():
    """懒加载 RAG 检索器"""
    try:
        from ..core.config import config
        if config.rag.enabled:
            from ..rag.retriever import RAGRetriever
            return RAGRetriever(config.rag)
    except Exception as e:
        logger.warning(f"RAG 检索器初始化失败: {e}")
    return None


class PersonaInjector:
    """
    人格注入引擎

    功能：
    1. 将人格画像转换为 LLM 可理解的提示词
    2. 注入口头禅、语法偏好、逻辑架构、时间模式
    3. 添加术语锁定约束
    4. 添加气口标记（[PAUSE]）控制

    使用流程：
    injector = PersonaInjector(llm_adapter)
    result = await injector.inject(source_text, persona_profile, locked_terms)
    """

    def __init__(self, llm_adapter: MiniMaxAdapter):
        """
        初始化人格注入引擎

        Args:
            llm_adapter: MiniMax 适配器实例
        """
        self.llm_adapter = llm_adapter
        self.term_lock = TermLock()

    async def inject(
        self,
        source_text: str,
        persona_profile: PersonalityProfile,
        locked_terms: list[str] | None = None,
        include_pauses: bool = True,
        target_hook_type: str | None = None,
        topic_technique: TopicTechnique | None = None,
        structure_map: ContentStructureMap | None = None,
    ) -> dict[str, Any]:
        """
        执行人格注入重写（编导+演员双轨架构）

        流程：
        1. 术语锁定
        2. 阶段一（编导）：生成黄金 Hook，带反思重试环
        3. 阶段二（演员）：续写正文
        4. 物理拼接 + 术语恢复

        当提供技法参数时，使用「技法驱动 + 风格驱动」双轨模式。

        Args:
            source_text: 原始素材文本
            persona_profile: 人格画像
            locked_terms: 额外需要保护的术语
            include_pauses: 是否注入停顿标记
            target_hook_type: 指定钩子类型（可选）
            topic_technique: 选题技法（可选）
            structure_map: 内容结构映射（可选）

        Returns:
            {
                "hook_strategy": "使用的Hook策略",
                "rewritten_text": "重写后的文本",
                "pause_markers": ["[PAUSE]位置列表"],
                "style_notes": "风格说明",
                "term_lock_result": TermLockResult,
                "term_preservation": {...}
            }

        Raises:
            PersonaInjectionError: 注入失败
        """
        try:
            # Step 1: 术语锁定
            lock_result = self.term_lock.lock_terms(source_text)
            protected_text = lock_result.protected_text

            # 合并锁定术语
            all_locked_terms = list(lock_result.locked_terms)
            if locked_terms:
                all_locked_terms.extend(locked_terms)
            all_locked_terms = list(set(all_locked_terms))  # 去重

            # 实例化 Scorer（用于 Hook 评分）
            from ..audit.scorer import ConsistencyScorer
            from ..audit.reverse_agent import ReverseAgent

            # 注入 ReverseAgent 到 Scorer
            reverse_agent_instance = ReverseAgent(llm_adapter=self.llm_adapter)
            scorer = ConsistencyScorer(reverse_agent=reverse_agent_instance)

            # Step 2: 编导上场 -> 生成黄金 Hook（带反思重试环）
            max_hook_retries = 3
            hook_feedback = None
            golden_hook = ""
            hook_strategy = ""

            # 新增：记录最高分的失败品
            best_failed_hook = ""
            highest_score = -1.0

            for attempt in range(max_hook_retries):
                hook_result = await self.llm_adapter.generate_hook(
                    source_text=protected_text,
                    protected_terms=all_locked_terms,
                    previous_feedback=hook_feedback,
                )

                # 如果指定了钩子类型，验证生成结果是否匹配
                if target_hook_type and attempt < max_hook_retries - 1:
                    generated_hook = hook_result.get("golden_hook", "")
                    if not self._hook_type_matches(generated_hook, target_hook_type):
                        hook_feedback = (
                            f"你刚才生成的句子是『{generated_hook}』。"
                            f"被拒原因：钩子类型不匹配，要求 {target_hook_type} 类型，但生成的不符合。"
                            f"请换用 {target_hook_type} 策略重新生成！"
                        )
                        logger.warning(f"Hook 类型不匹配 (第 {attempt + 1} 次): {hook_feedback}")
                        continue

                candidate_hook = hook_result.get("golden_hook", "")
                score_result = scorer._score_golden_hook(candidate_hook)

                if score_result["score"] == 100.0:
                    golden_hook = candidate_hook
                    hook_strategy = hook_result.get("strategy", "")
                    logger.info(f"Hook 生成成功 (尝试次数: {attempt + 1})")
                    break
                else:
                    # 缓存得分最高的失败品（比如得分50的长句子，总比得分0的AI味句子好）
                    if score_result["score"] > highest_score:
                        highest_score = score_result["score"]
                        best_failed_hook = candidate_hook

                    hook_feedback = (
                        f"你刚才生成的句子是『{candidate_hook}』。 "
                        f"被拒原因：{score_result['reason']}。请换一个切入点！"
                    )
                    logger.warning(f"Hook 被打回 (第 {attempt + 1} 次尝试): {hook_feedback}")

            # 兜底降级（完整降级矩阵）
            if not golden_hook:
                if highest_score > 0:
                    # 策略A：使用只犯了小错（如过长）的次优 Hook
                    logger.error(f"Hook 生成未达满分，降级使用次优品 (得分: {highest_score})")
                    golden_hook = best_failed_hook
                    hook_strategy = "降级次优品"
                else:
                    # 策略B：NLP提取+模板填充（零成本、零幻觉）
                    logger.error("Hook 生成全军覆没，启动NLP+模板降级。")
                    golden_hook = self._get_nlp_fallback_hook(protected_text)
                    hook_strategy = "降级NLP模板"

                    # 策略C：NLP也失败了，最后防线正则硬清洗
                    if not golden_hook:
                        logger.error("NLP降级也失败，启动最后防线正则硬清洗。")
                        golden_hook = self._get_safe_fallback_hook(protected_text)
                        hook_strategy = "降级规则清洗"

            # Step 3: 演员上场 -> 续写正文 (带语义打分与反思环，最高重试3次)
            persona_prompt_dict = self._build_persona_prompt(persona_profile)

            # RAG 检索：查找相似的真实语料作为 few-shot 示例
            few_shot_examples = None
            rag_retriever = _get_rag_retriever()
            if rag_retriever:
                rag_results = rag_retriever.retrieve_similar(
                    query_text=protected_text,
                    persona_id=persona_profile.id,
                    top_k=3,
                )
                if rag_results:
                    # 转换为 build_body_rewrite_prompt 期望的格式
                    few_shot_examples = [
                        {"content": r["document"]}
                        for r in rag_results
                    ]
                    logger.info(f"RAG 检索到 {len(few_shot_examples)} 条相似语料，将作为 few-shot 示例")

            max_body_retries = 3
            body_feedback = None
            rewritten_body = ""
            body_res_data = {}

            for body_attempt in range(max_body_retries):
                # 技法驱动模式：使用 prompt_library 的双轨模板
                if topic_technique or structure_map:
                    from ..technique.prompt_library import build_technique_driven_rewrite_prompt
                    from ..core.types import HookAnalysis, HookType

                    hook_analysis = HookAnalysis(
                        hook_text=golden_hook,
                        hook_type=HookType(target_hook_type) if target_hook_type else HookType.REVERSE_LOGIC,
                        psychological_mechanism="",
                        structural_formula="",
                        why_it_works="",
                        reconstruction_template="",
                    )
                    body_prompt = build_technique_driven_rewrite_prompt(
                        source_text=protected_text,
                        hook_analysis=hook_analysis,
                        persona=persona_profile,
                        topic_technique=topic_technique,
                        structure_map=structure_map,
                        few_shot_examples=few_shot_examples,
                    )
                else:
                    body_prompt = self.llm_adapter.build_body_rewrite_prompt(
                        source_text=protected_text,
                        golden_hook=golden_hook,
                        persona_profile=persona_prompt_dict,
                        protected_terms=all_locked_terms,
                        few_shot_examples=few_shot_examples,
                        previous_feedback=body_feedback,
                    )

                body_res = await self.llm_adapter.generate_json(
                    prompt=body_prompt,
                    system_prompt="你是一个专业的配音演员与模仿专家。"
                )
                candidate_body = body_res.get("rewritten_body", "")

                # 调用大模型进行神似度语义打分
                vibe_eval = await scorer._score_semantic_vibe(candidate_body, persona_profile)

                if vibe_eval["score"] >= 85.0:
                    rewritten_body = candidate_body
                    body_res_data = body_res
                    logger.info(f"正文神似度达标 ({vibe_eval['score']}分), 尝试次数: {body_attempt + 1}")
                    break
                else:
                    body_feedback = f"神似度打分仅 {vibe_eval['score']}。评委反馈：{vibe_eval['reason']}。请重写！"
                    logger.warning(f"正文被打回 (第 {body_attempt + 1} 次): {body_feedback}")

            # 兜底降级逻辑：如果几次都没达标，强行采用最后一次生成的结果
            if not rewritten_body:
                logger.error("正文多次重写均未达到完美神似度，使用最终生成版本兜底。")
                rewritten_body = candidate_body
                body_res_data = body_res

            # Step 4: 物理拼接隔离（Hook + [PAUSE] + Body）
            combined_text = f"{golden_hook}[PAUSE] {rewritten_body}"

            # Step 5: 恢复术语
            final_text = self.term_lock.restore_terms(
                combined_text,
                lock_result.locked_map,
            )

            return {
                "hook_strategy": hook_strategy,
                "rewritten_text": final_text,
                "pause_markers": body_res_data.get("pause_markers", []),
                "style_notes": body_res_data.get("style_notes", ""),
                "term_lock_result": lock_result,
                "term_preservation": {
                    "preserved": [],
                    "violated_terms": [],
                    "all_locked_terms": all_locked_terms,
                },
            }

        except Exception as e:
            raise PersonaInjectionError(
                message=f"Persona injection failed: {str(e)}",
                persona_id=persona_profile.id,
                details={"error_type": type(e).__name__},
            )

    def _build_persona_prompt(self, profile: PersonalityProfile) -> dict[str, Any]:
        """
        将人格画像转换为 LLM 可理解的字典格式

        Args:
            profile: 人格画像

        Returns:
            用于提示词的人格特征字典
        """
        return {
            "name": profile.name,
            "verbal_tics": profile.verbal_tics,
            "grammar_prefs": profile.grammar_prefs,
            "logic_architecture": {
                "opening_style": profile.logic_architecture.opening_style,
                "transition_patterns": profile.logic_architecture.transition_patterns,
                "closing_style": profile.logic_architecture.closing_style,
                "topic_organization": profile.logic_architecture.topic_organization,
            },
            "temporal_patterns": {
                "speech_rhythm": profile.temporal_patterns.speech_rhythm,
                "pause_frequency": profile.temporal_patterns.pause_frequency,
                "avg_pause_duration": profile.temporal_patterns.avg_pause_duration,
            },
            "deep_psychology": {
                "emotional_tone": profile.deep_psychology.emotional_tone,
                "emotional_arc": profile.deep_psychology.emotional_arc,
                "rhetorical_devices": profile.deep_psychology.rhetorical_devices,
                "lexicon": profile.deep_psychology.lexicon,
            },
            "injection_instructions": self._generate_injection_instructions(profile),
        }

    def _generate_injection_instructions(self, profile: PersonalityProfile) -> str:
        """
        生成人格注入指令

        将人格特征转换为自然语言指令，引导 LLM 复现该风格。

        Args:
            profile: 人格画像

        Returns:
            注入指令字符串
        """
        instructions = []

        # 口头禅指令
        if profile.verbal_tics:
            tics_str = "、".join(profile.verbal_tics[:5])
            instructions.append(
                f"口头禅：适度使用 {tics_str} 等语气词，增强亲切感"
            )

        # 语法偏好指令
        if profile.grammar_prefs:
            prefs_str = "；".join(profile.grammar_prefs[:3])
            instructions.append(f"语法偏好：{prefs_str}")

        # 逻辑架构指令
        arch = profile.logic_architecture
        instructions.append(f"开场风格：{arch.opening_style}")
        instructions.append(f"过渡方式：{'、'.join(arch.transition_patterns) if arch.transition_patterns else '自然过渡'}")
        instructions.append(f"结尾风格：{arch.closing_style}")

        # 时间模式指令
        temp = profile.temporal_patterns
        instructions.append(
            f"节奏控制：{temp.speech_rhythm}节奏，"
            f"每分钟约{temp.pause_frequency}次停顿"
        )

        return "\n".join(instructions)

    @staticmethod
    def _hook_type_matches(hook_text: str, target_type: str) -> bool:
        """
        简单规则校验钩子类型是否匹配（轻量级，不调用 LLM）

        用于快速过滤明显不匹配的钩子。
        """
        text = hook_text.strip()

        type_indicators = {
            "reverse_logic": ["不是", "根本", "其实", "从来没", "别再"],
            "pain_point": ["还在", "你是不是", "有没有", "是不是也"],
            "benefit_bomb": ["秒", "分钟", "一步", "只需", "搞定"],
            "suspense_cutoff": ["因为", "但是", "后来", "结果"],
            "authority_subvert": ["专家", "教授", "巴菲特", "大佬"],
            "data_impact": ["%", "万", "亿", "倍", "差距"],
            "identity_label": ["如果你也", "你是", "这类人", "像你这样"],
        }

        indicators = type_indicators.get(target_type, [])
        return any(ind in text for ind in indicators)

    def _get_safe_fallback_hook(self, source_text: str) -> str:
        """
        安全提取降级Hook：硬清洗原文废话前缀

        当3次Hook生成均失败时，使用此方法从原文首句提取"相对干净"的降级Hook。
        通过循环刮除AI味黑名单词汇，确保至少不是一个废话开场。

        Args:
            source_text: 原始素材文本

        Returns:
            清洗后的降级Hook（最多20字）
        """
        ai_smell_blacklist = [
            "今天我们", "众所周知", "你知道吗", "敢相信",
            "探讨一下", "随着社会", "在这个时代", "大家好",
            "首先", "然后", "接下来", "也就是说", "其实",
        ]

        # 提取第一句话（按句号、感叹号、问号分割）
        first_sentence = source_text.split('。')[0].split('！')[0].split('？')[0]

        # 循环刮除句首的废话词汇
        clean_text = first_sentence.strip(' ，。、\n')
        changed = True
        while changed:
            changed = False
            for word in ai_smell_blacklist:
                if clean_text.startswith(word):
                    # 切掉废话，并移除紧跟的标点
                    clean_text = clean_text[len(word):].strip(' ，。、')
                    changed = True
                    break

        # 截取刮骨疗毒后的前20个字
        final_hook = clean_text.split('，')[0][:20]

        # 如果刮完后啥都不剩了，尝试拿后面一句话兜底
        if not final_hook:
            # 尝试用第二句话
            remaining = source_text[len(first_sentence):]
            second_sentence = remaining.split('。')[0].split('，')[0][:20]
            return second_sentence if second_sentence else source_text[20:40].split('，')[0]

        return final_hook

    def _get_nlp_fallback_hook(self, source_text: str) -> str:
        """
        第三级降级：NLP关键词提取 + 静态模板填充

        当LLM 3次生成和正则清洗都失败时，使用此方法：
        1. 用轻量级NLP（jieba）从原文提取核心关键词
        2. 将关键词填入预制的安全模板
        3. 返回组装后的Hook

        优点：
        - 零Token消耗（纯本地CPU计算，几毫秒级）
        - 零幻觉风险（模板是人类写的）
        - 保留核心语义（从原文提取）

        Args:
            source_text: 原始素材文本

        Returns:
            由关键词+模板组装的安全Hook
        """
        try:
            import jieba
            import random
        except ImportError:
            # jieba未安装，降级到正则清洗
            return self._get_safe_fallback_hook(source_text)

        # 1. 用jieba提取关键词（TF-IDF风格）
        # 移除停用词
        stopwords = {
            '的', '了', '是', '在', '我', '有', '和', '就', '不', '人',
            '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去',
            '你', '会', '着', '没有', '看', '好', '自己', '这', '那', '他',
        }

        # 分词并过滤
        words = [w for w in jieba.cut(source_text) if len(w) >= 2 and w not in stopwords]

        # 统计词频
        word_freq = {}
        for w in words:
            word_freq[w] = word_freq.get(w, 0) + 1

        # 取频率最高的2-3个词
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        top_words = [w for w, _ in sorted_words[:3]]

        # 确保有关键词
        if not top_words:
            return self._get_safe_fallback_hook(source_text)

        word1 = top_words[0] if len(top_words) > 0 else ""
        word2 = top_words[1] if len(top_words) > 1 else top_words[0]
        word3 = top_words[2] if len(top_words) > 2 else word2

        # 2. 预制安全模板（绝对无AI味）
        templates = [
            "关于 {w1} 和 {w2}，有个关键点你必须知道",
            "今天只讲一件事：{w1}",
            "{w1} 这个问题，核心就三点",
            "{w1} 和 {w2}，到底什么关系？",
            "说透 {w1}，只需三点",
        ]

        # 3. 随机组装
        template = random.choice(templates)
        hook = template.format(w1=word1, w2=word2, w3=word3)

        # 截取到合理长度（不超过25字）
        if len(hook) > 25:
            hook = hook[:25]

        logger.info(f"NLP降级生成Hook: {hook} (关键词: {top_words})")
        return hook

    async def batch_inject(
        self,
        source_text: str,
        persona_profiles: list[PersonalityProfile],
        locked_terms: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        批量注入：使用多个人格同时重写同一文本

        Args:
            source_text: 原始素材文本
            persona_profiles: 人格画像列表
            locked_terms: 需要保护的术语

        Returns:
            各个人格的重写结果列表
        """
        results = []
        for profile in persona_profiles:
            try:
                result = await self.inject(
                    source_text=source_text,
                    persona_profile=profile,
                    locked_terms=locked_terms,
                )
                result["persona_id"] = profile.id
                result["persona_name"] = profile.name
                result["success"] = True
            except PersonaInjectionError as e:
                result = {
                    "persona_id": profile.id,
                    "persona_name": profile.name,
                    "success": False,
                    "error": str(e),
                }
            results.append(result)

        return results

    def build_verification_prompt(
        self,
        original_profile: PersonalityProfile,
        rewritten_text: str,
    ) -> str:
        """
        构建验证提示词（用于一致性评分）

        Args:
            original_profile: 原始人格画像
            rewritten_text: 重写后的文本

        Returns:
            验证提示词
        """
        return f"""## 任务
评估以下文案是否符合指定作者的风格。

## 作者风格画像
- 口头禅：{', '.join(original_profile.verbal_tics[:5]) if original_profile.verbal_tics else '无'}
- 语法偏好：{', '.join(original_profile.grammar_prefs[:3]) if original_profile.grammar_prefs else '无'}
- 开场风格：{original_profile.logic_architecture.opening_style}
- 过渡方式：{', '.join(original_profile.logic_architecture.transition_patterns) if original_profile.logic_architecture.transition_patterns else '无'}
- 结尾风格：{original_profile.logic_architecture.closing_style}
- 节奏：{original_profile.temporal_patterns.speech_rhythm}节奏

## 待评估文案
{rewritten_text}

## 评估维度
1. 口头禅命中：原口头禅在文中的出现情况
2. 语法相似度：句式结构是否相似
3. 逻辑流畅度：开场、过渡、结尾是否连贯
4. 节奏契合度：停顿和语速是否匹配

请以 JSON 格式返回评估结果：
{{
    "verbal_tic_match": 0.85,
    "grammar_similarity": 0.80,
    "logic_flow": 0.90,
    "rhythm_fit": 0.75,
    "overall_score": 0.825,
    "feedback": "具体反馈"
}}
"""

"""
MiniMax API 适配器

提供统一的接口调用 MiniMax 大模型，支持结构化 JSON 输出
"""

import json
import logging
from typing import Any

import httpx

from ..core.config import config
from ..core.exceptions import JSONParseError, ModelAPIError


logger = logging.getLogger(__name__)


def extract_json_with_stack(text: str) -> dict:
    """
    使用栈结构提取最完整的 JSON 对象

    解决嵌套 JSON 的匹配问题（如 {a: {b: 1}}）

    Args:
        text: 原始输出文本

    Returns:
        解析后的 JSON 字典

    Raises:
        ValueError: 无法解析为有效 JSON
    """
    text = text.strip()

    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 找最外层 { }
    start = text.find('{')
    if start == -1:
        raise ValueError("No JSON object found in response")

    depth = 0
    end = -1
    for i, c in enumerate(text[start:], start):
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                end = i
                break

    if end == -1:
        raise ValueError("Invalid JSON structure: unmatched braces")

    json_str = text[start:end + 1]

    # 移除 markdown 代码块标记
    if json_str.startswith('```'):
        lines = json_str.split('\n')
        if lines[0].strip().startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        json_str = '\n'.join(lines)

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse JSON: {e}")


class MiniMaxAdapter:
    """
    MiniMax API 适配器

    功能：
    1. 调用 MiniMax Chat API 进行文本生成
    2. 强制 JSON 结构化输出，减少解析难度
    3. 支持异步调用
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ):
        """
        初始化 MiniMax 适配器

        Args:
            api_key: API Key（默认从配置读取）
            base_url: API 基础 URL
            model: 模型名称
            timeout: 请求超时（秒）
        """
        minimax_config = config.minimax

        self.api_key = api_key or minimax_config.api_key
        self.base_url = base_url or minimax_config.base_url
        self.model = model or minimax_config.model
        self.timeout = timeout or minimax_config.timeout

        if not self.api_key:
            raise ValueError("MiniMax API key is required")

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """
        调用 MiniMax API 生成文本

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            temperature: 温度参数 (0.0-1.0)
            max_tokens: 最大生成 token 数

        Returns:
            生成的文本

        Raises:
            ModelAPIError: API 调用失败
            JSONParseError: JSON 解析失败
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/text/chatcompletion_v2",
                    headers=headers,
                    json=payload,
                )

                if response.status_code != 200:
                    raise ModelAPIError(
                        message=f"MiniMax API error: {response.status_code}",
                        provider="minimax",
                        status_code=response.status_code,
                        details={"response": response.text[:500]},
                    )

                result = response.json()
                return result["choices"][0]["message"]["content"]

        except httpx.TimeoutException as e:
            raise ModelAPIError(
                message=f"MiniMax API timeout: {str(e)}",
                provider="minimax",
                details={"timeout": self.timeout},
            )
        except httpx.HTTPError as e:
            raise ModelAPIError(
                message=f"MiniMax API HTTP error: {str(e)}",
                provider="minimax",
            )

    async def generate_json(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        """
        调用 MiniMax API 并强制 JSON 结构化输出

        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            temperature: 温度参数

        Returns:
            解析后的 JSON 字典

        Raises:
            ModelAPIError: API 调用失败
            JSONParseError: JSON 解析失败
        """
        # 强化系统提示词
        json_system_prompt = system_prompt or ""
        json_system_prompt += "\nStrictly output JSON. No markdown prefix/suffix."

        raw_output = await self.generate(
            prompt=prompt,
            system_prompt=json_system_prompt,
            temperature=temperature,
        )

        try:
            return extract_json_with_stack(raw_output)
        except ValueError as e:
            raise JSONParseError(
                message=f"Failed to parse JSON: {str(e)}",
                raw_response=raw_output[:1000],
            )

    def build_rewrite_prompt(
        self,
        source_text: str,
        persona_profile: dict[str, Any],
        protected_terms: list[str] | None = None,
    ) -> str:
        """
        构建重写提示词（优化版）

        Args:
            source_text: 原始素材文本
            persona_profile: 人格画像字典
            protected_terms: 已用【PROTECTED_TERM_n】格式保护的术语列表

        Returns:
            完整的提示词
        """
        # 获取人格画像信息
        verbal_tics = persona_profile.get("verbal_tics", [])
        grammar_prefs = persona_profile.get("grammar_prefs", [])
        logic_arch = persona_profile.get("logic_architecture", {})
        tempo = persona_profile.get("temporal_patterns", {})
        injection_instructions = persona_profile.get("injection_instructions", "")
        pause_density = tempo.get("pause_frequency", 5)

        # 术语保护要求
        terms_str = ", ".join(protected_terms) if protected_terms else "无"
        if terms_str == "无":
            terms_str = "无（所有术语已用【PROTECTED_TERM_n】占位符保护）"

        # 准备示例数据
        example_tic1 = verbal_tics[0] if verbal_tics else '哎呀'
        example_tic2 = verbal_tics[1] if len(verbal_tics) > 1 else '这个'
        example_grammar = ' '.join(grammar_prefs[:2]) if grammar_prefs else '短句为主'
        example_rhythm = tempo.get('speech_rhythm', 'medium')

        prompt = f"""# Role
你是一个短视频人格重构专家。

# Target Persona
- 叙事逻辑: {logic_arch.get('topic_organization', '线性叙述')}
- 过渡模式: {', '.join(logic_arch.get('transition_patterns', [])) or '常用连接词'}
- 节奏: {tempo.get('speech_rhythm', 'medium')} (约每分钟 {pause_density} 次停顿)

# Grammar Preference
语法偏好：{', '.join(grammar_prefs) if grammar_prefs else '无特定偏好'}

# Injection Instructions
{injection_instructions if injection_instructions else '按上述人格特征进行重写，保持风格一致'}

# Constraint
1. 【重要】术语保护：已用【PROTECTED_TERM_n】格式保护的词汇必须原样保留，禁止任何替换或修改，【大小写敏感】
2. 节奏：在逻辑停顿处插入 [PAUSE] 标签，频率约每分钟 {pause_density} 次
3. 口头禅：自然融入以下词汇：{', '.join(verbal_tics[:5]) if verbal_tics else '无'}
4. 语法偏好：{', '.join(grammar_prefs) if grammar_prefs else '保持语句通顺'}

# Source Material
{source_text}

# Output Format
严格以 JSON 格式返回：
{{
    "rewritten_text": "重写后的文本（必须包含[PAUSE]标签）",
    "pause_markers": ["[PAUSE]标签在文本中的位置描述，如：在逗号后"],
    "style_notes": "本次重写的风格说明"
}}

# Few-shot Example
<examples>
输入: 哎呀，这把枪真的超厉害，射速全游戏最快
<output>
{{"rewritten_text": "{example_tic1}，{example_tic2}枪是真的猛啊[PAUSE]射速全游戏第一[PAUSE]你没听错", "pause_markers": ["在'枪'字后", "在'第一'后"], "style_notes": "融入了口头禅，保持了快节奏"}}
</output>
</examples>

# Self-Verification (请在返回JSON前完成)
1. 检查输出是否包含所有口头禅词汇
2. 检查术语保护是否完整（【PROTECTED_TERM_n】未被修改）
3. 检查[PAUSE]标签数量是否符合目标频率
只有确认所有检查通过后，才返回最终JSON结果。"""
        return prompt

    async def rewrite(
        self,
        source_text: str,
        persona_profile: dict[str, Any],
        protected_terms: list[str] | None = None,
        locked_terms: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        执行文案重写

        Args:
            source_text: 原始素材
            persona_profile: 人格画像
            protected_terms: 已保护的术语列表（主参数）
            locked_terms: 已保护的术语列表（别名，与 protected_terms 等效）

        Returns:
            包含 rewritten_text, pause_markers 等字段的字典

        Raises:
            ModelAPIError: API 调用失败
            JSONParseError: JSON 解析失败
        """
        # 处理 locked_terms 别名
        if protected_terms is None and locked_terms is not None:
            protected_terms = locked_terms

        prompt = self.build_rewrite_prompt(
            source_text=source_text,
            persona_profile=persona_profile,
            protected_terms=protected_terms,
        )

        system_prompt = """你是一个专业的文风模仿专家，擅长分析并复现特定作者的语言风格、叙事逻辑和表达习惯。"""

        return await self.generate_json(prompt=prompt, system_prompt=system_prompt)

    async def extract_persona_features(self, texts: list[str]) -> dict[str, Any]:
        """
        从多篇文本中提取人格特征（AI 辅助）

        Args:
            texts: 文本列表

        Returns:
            人格特征字典

        Raises:
            ModelAPIError: API 调用失败
            JSONParseError: JSON 解析失败
        """
        combined_texts = "\n\n---\n\n".join([f"[{i+1}] {t}" for i, t in enumerate(texts)])

        prompt = f"""## 任务
分析以下文案，提取该作者的人格特征。

## 文案列表
{combined_texts}

## 输出格式
严格以 JSON 格式返回：
{{
    "verbal_tics": ["口头禅列表"],
    "grammar_prefs": ["语法偏好列表"],
    "logic_architecture": {{
        "opening_style": "开场风格",
        "transition_patterns": ["过渡模式"],
        "closing_style": "结尾风格",
        "topic_organization": "话题组织方式"
    }},
    "temporal_patterns": {{
        "speech_rhythm": "语速节奏(fast/medium/slow)",
        "pause_frequency": "停顿频率(次/分钟)"
    }}
}}
"""

        system_prompt = """你是一个专业的人格分析师，擅长从文本中提取作者的语言风格特征。"""

        return await self.generate_json(prompt=prompt, system_prompt=system_prompt)

    async def reverse_extract(self, text: str) -> dict[str, Any]:
        """
        反向推导：根据生成的文案提取人格特征

        Args:
            text: 需要分析的文案

        Returns:
            推测的人格特征

        Raises:
            ModelAPIError: API 调用失败
            JSONParseError: JSON 解析失败
        """
        prompt = f"""## 任务
根据以下文案，反向推测该作者的人格特征。

## 文案
{text}

## 输出格式
严格以 JSON 格式返回：
{{
    "verbal_tics": ["推测的口头禅列表"],
    "grammar_prefs": ["推测的语法偏好"],
    "logic_architecture": {{
        "opening_style": "推测的开场风格",
        "transition_patterns": ["推测的过渡模式"],
        "closing_style": "推测的结尾风格"
    }},
    "estimated_wpm": "估计的语速"
}}
"""

        system_prompt = """你是一个专业的人格分析师，擅长从文本风格反向推断作者特征。"""

        return await self.generate_json(prompt=prompt, system_prompt=system_prompt)

    async def generate_hook(
        self,
        source_text: str,
        protected_terms: list = None,
        previous_feedback: str = None,
    ) -> dict[str, Any]:
        """
        【阶段一】：生成带反思机制的黄金 3 秒 Hook

        Args:
            source_text: 原始素材文本
            protected_terms: 需要保护的术语列表
            previous_feedback: 上次生成失败的反馈（如有）

        Returns:
            {
                "strategy": "使用的Hook策略",
                "golden_hook": "生成的开场文案"
            }
        """
        terms_str = ", ".join(protected_terms) if protected_terms else "无"
        if terms_str == "无":
            terms_str = "无（所有术语已用【PROTECTED_TERM_n】占位符保护）"

        prompt = f"""# Role
你是一个千万级粉丝短视频账号的金牌编导，最擅长极其抓人眼球的"黄金3秒"开场。

# Task
阅读下方的【原始素材】，为其提炼/重写一个最具爆发力的前3秒开场（约15-25个汉字）。
"""
        # 反思机制注入
        if previous_feedback:
            prompt += f"""
# ⚠️ CRITICAL WARNING (上次生成失败反馈) ⚠️
你上一次生成的文案被主编打了回来！反馈是：【{previous_feedback}】
请务必吸取教训！绝对禁止犯同样的错误！换一种完全不同的 Hook 策略！
"""

        prompt += f"""
# Hook Strategy Constraints (必须且只能使用以下策略之一)
1. 痛点前置：直接刺痛目标受众最焦虑的问题。
2. 反常识冲击：打破常规认知，制造强烈反差。
3. 核心悬念：把最违背直觉的结论放在第一句，但不说原因。

# Negative Constraints (触发即为严重事故)
- 绝对禁止使用："今天我们"、"你知道吗"、"你敢相信吗"、"众所周知"等浓重AI味的陈词滥调。
- 绝对禁止使用四平八稳的总结。
- 必须原样保留占位符【PROTECTED_TERM_n】。

# Source Material
{source_text}

# Output Format
严格以 JSON 格式返回：
{{
    "strategy": "简述你使用的Hook策略",
    "golden_hook": "重写后的开场文案（极具冲击力）"
}}"""
        system_prompt = "你是一个深谙人性与短视频流量密码的顶级编导。"
        return await self.generate_json(prompt=prompt, system_prompt=system_prompt)

    def build_body_rewrite_prompt(
        self,
        source_text: str,
        golden_hook: str,
        persona_profile: dict,
        protected_terms: list = None,
        few_shot_examples: list[dict] = None,
        previous_feedback: str = None,
    ) -> str:
        """
        【阶段二】：基于 Hook 的正文续写 Prompt (含多模态与心理学特征)

        Args:
            source_text: 原始素材文本
            golden_hook: 已确定的黄金开场白
            persona_profile: 人格画像字典
            protected_terms: 需要保护的术语列表
            few_shot_examples: 动态 RAG 示例接入点（可选）
            previous_feedback: 反思机制接入点（可选）

        Returns:
            构建好的提示词字符串
        """
        verbal_tics = persona_profile.get("verbal_tics", [])
        grammar_prefs = persona_profile.get("grammar_prefs", [])
        logic_arch = persona_profile.get("logic_architecture", {})
        tempo = persona_profile.get("temporal_patterns", {})
        pause_density = tempo.get("pause_frequency", 5)

        # 新增：深度心理学特征
        deep_psy = persona_profile.get("deep_psychology", {})
        emotional_tone = deep_psy.get("emotional_tone", "平稳中立")
        lexicon = deep_psy.get("lexicon", [])
        rhetorical_devices = deep_psy.get("rhetorical_devices", [])

        prompt = f"""# Role
你是一个短视频人格重构与配音导演专家。

# Target Persona
- 情感基调: {emotional_tone}
- 叙事逻辑: {logic_arch.get('topic_organization', '线性叙述')}
- 过渡模式: {', '.join(logic_arch.get('transition_patterns', [])) or '常用连接词'}
- 节奏: {tempo.get('speech_rhythm', 'medium')} (约每分钟 {pause_density} 次停顿)
- 专属词汇: 自然融入 {', '.join(lexicon[:8]) if lexicon else '无特定'}
- 修辞偏好: 擅长使用 {', '.join(rhetorical_devices) if rhetorical_devices else '常规陈述'}
- 语法偏好：{', '.join(grammar_prefs) if grammar_prefs else '无特定偏好'}
- 口头禅：自然融入 {', '.join(verbal_tics[:5]) if verbal_tics else '无'}
"""

        # 反思机制注入
        if previous_feedback:
            prompt += f"""
# ⚠️ CRITICAL WARNING (上次重写被拒反馈)
评委反馈：【{previous_feedback}】
请务必调整策略，修复上述问题！绝对禁止重犯！
"""

        prompt += f"""
# Context & Task
确定开场白：【{golden_hook}】
任务：接续开场白，用上述人格重写剩余素材。

# Multimodal Constraints (配音表现力标签)
你必须在自然的位置插入以下方括号标签：
1. [PAUSE]: 逻辑停顿
2. [EMPHASIS]: 重读词汇前
3. [LAUGH]: 标志性笑声或冷笑处
4. [SPEED_UP] / [SLOW_DOWN]: 语速需要突变拉扯情绪的起点

# Constraint
1. 术语保护：【PROTECTED_TERM_n】必须原样保留，禁止任何替换或修改，【大小写敏感】
2. 绝对不能重复开场白的意思。
3. 平滑过渡：第一句话必须能跟开场白自然接上。

# Source Material
{source_text}
"""

        # 动态 RAG 注入
        if few_shot_examples:
            prompt += "\n# Reference Examples (目标博主真实语料参考)\n<examples>\n"
            for ex in few_shot_examples:
                prompt += f"真实语料: {ex.get('content', '')}\n---\n"
            prompt += "</examples>\n"

        prompt += """
# Output Format (Strict JSON)
{
    "rewritten_body": "重写后的正文（必须包含上述配音表现力标签）",
    "paralanguage_density": "标签使用统计",
    "style_notes": "情绪曲线说明"
}

# Self-Verification (请在返回JSON前完成)
1. 检查输出是否包含目标博主的专属词汇
2. 检查术语保护是否完整（【PROTECTED_TERM_n】未被修改）
3. 检查[PAUSE]标签数量是否符合目标频率
4. 检查是否使用了至少2种配音表现力标签
只有确认所有检查通过后，才返回最终JSON结果。"""
        return prompt

    async def rewrite_body(
        self,
        source_text: str,
        golden_hook: str,
        persona_profile: dict,
        protected_terms: list = None,
        few_shot_examples: list[dict] = None,
        previous_feedback: str = None,
    ) -> dict[str, Any]:
        """
        【阶段二】：续写正文

        Args:
            source_text: 原始素材文本
            golden_hook: 已确定的黄金开场白
            persona_profile: 人格画像字典
            protected_terms: 需要保护的术语列表
            few_shot_examples: 动态 RAG 示例（可选）
            previous_feedback: 上次生成反馈（可选，用于反思环）

        Returns:
            包含 rewritten_body, paralanguage_density, style_notes 的字典
        """
        prompt = self.build_body_rewrite_prompt(
            source_text=source_text,
            golden_hook=golden_hook,
            persona_profile=persona_profile,
            protected_terms=protected_terms,
            few_shot_examples=few_shot_examples,
            previous_feedback=previous_feedback,
        )
        system_prompt = "你是一个专业的配音演员与模仿专家。"
        return await self.generate_json(prompt=prompt, system_prompt=system_prompt)

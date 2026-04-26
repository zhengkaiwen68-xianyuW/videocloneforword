"""
技法驱动的 Prompt 模板库

提供「技法驱动 + 风格驱动」双轨 Prompt 模板，用于重写引擎。
"""

from typing import Any

from ..core.types import (
    ContentStructureMap,
    HookAnalysis,
    HookType,
    PersonalityProfile,
    TopicTechnique,
)


def build_topic_analysis_prompt(texts: list[str]) -> str:
    """构建选题技法分析 Prompt"""
    combined = "\n\n---\n\n".join([f"[视频 {i+1}]\n{t}" for i, t in enumerate(texts)])

    return f"""# Role
你是一位短视频内容策略分析师，擅长从大量视频文案中提炼选题规律。

# Task
分析以下 N 个视频的文案，提炼该作者的选题技法画像。

# Source Videos
{combined}

# Analysis Dimensions
1. **角度偏好**：该作者最喜欢从什么角度切入选题？（反常识/痛点前置/数据碾压/身份认同/经验分享 等）
2. **痛点图谱**：反复戳的痛点是什么？目标受众最焦虑什么？
3. **选题公式**：归纳出可复用的选题结构模板，如 "{{常识}} + 根本不是{{常识}}"
4. **选题筛选标准**：什么样的选题会被采用？有什么共性？
5. **选题禁区**：从不触碰的话题类型有哪些？

# Output Format
严格以 JSON 格式返回：
{{
    "angle_patterns": ["角度1", "角度2"],
    "pain_points": ["痛点1", "痛点2"],
    "topic_formulas": ["公式模板1", "公式模板2"],
    "selection_criteria": ["标准1", "标准2"],
    "avoid_patterns": ["禁区1", "禁区2"]
}}

# Self-Verification
1. 每个维度至少列出 2 项
2. 公式模板必须是可复用的结构，不能是具体案例
3. 禁区必须基于"从未触碰"而非"不擅长"
只有确认检查通过后，才返回最终 JSON。"""


def build_hook_deconstruct_prompt(
    hook_text: str,
    full_text: str = "",
) -> str:
    """构建钩子拆解 Prompt"""
    context_section = ""
    if full_text:
        context_section = f"""
# Full Video Context (供参考)
{full_text[:1000]}"""

    return f"""# Role
你是一位短视频流量密码研究专家，专门拆解"黄金3秒"钩子的底层机制。

# Task
拆解以下短视频开头文案的钩子技法。

# Hook Text
{hook_text}
{context_section}

# Hook Type Classification (选择最匹配的一种)
1. **reverse_logic** — 反逻辑：打破常识 ("Excel不用学")
2. **pain_point** — 痛点刺痛：直接戳焦虑 ("你还在用这种方法？")
3. **benefit_bomb** — 利益炸弹：极低成本极高认知 ("3秒搞定")
4. **suspense_cutoff** — 悬念断句：话说一半 ("这个方法99%的人不知道，因为...")
5. **authority_subvert** — 权威颠覆：借权威反权威 ("巴菲特说不要炒股，但他自己...")
6. **data_impact** — 数据冲击：用数字制造震撼 ("月薪3000和30000的区别只有...")
7. **identity_label** — 身份标签：给观众贴标签 ("如果你也是35岁还没...")

# Analysis Dimensions
1. 钩子类型分类（必须是上述 7 种之一）
2. 心理机制归因（认知失调 / 损失厌恶 / 社会比较 / 好奇心缺口 / 稀缺效应 / ...）
3. 结构公式提取（可复用的模板，用 {{变量}} 标记可替换部分）
4. 有效性分析（为什么这个钩子有效？触发了什么心理反应？）
5. 重建模板（如何用同样的公式写出新的钩子？）

# Output Format
严格以 JSON 格式返回：
{{
    "hook_type": "类型枚举值",
    "psychological_mechanism": "心理机制描述",
    "structural_formula": "可复用的结构公式模板",
    "why_it_works": "有效性分析",
    "reconstruction_template": "重建模板说明"
}}

# Self-Verification
1. hook_type 必须是 7 种枚举值之一
2. structural_formula 必须包含 {{变量}} 占位符
3. why_it_works 必须引用具体的心理学原理
只有确认检查通过后，才返回最终 JSON。"""


def build_structure_map_prompt(
    full_text: str,
    timestamps: list[dict] | None = None,
) -> str:
    """构建内容结构映射 Prompt"""
    timestamp_section = ""
    if timestamps:
        ts_str = "\n".join([f"  {t.get('time', '')}: {t.get('text', '')}" for t in timestamps[:30]])
        timestamp_section = f"\n# Timestamps\n{ts_str}"

    return f"""# Role
你是一位短视频内容结构分析师，擅长拆解视频的"操控地图"。

# Task
分析以下完整视频文案，提取其内容结构映射。

# Full Text
{full_text}
{timestamp_section}

# Analysis Dimensions
1. **信任建立段**：作者如何建立可信度？（数据引用/经验展示/权威背书/...）
2. **痛点放大段**：如何放大受众的焦虑/需求？
3. **信息密度曲线**：标注高密度输出 vs 低密度留白的时间段分布
4. **情绪操控节点**：完整的情绪链路（如：好奇 -> 焦虑 -> 释然 -> 紧迫）
5. **CTA 收尾模式**：视频如何收尾？（引导关注/留悬念/总结升华/...）
6. **收尾情绪**：最后一句话营造的情绪是什么？

# Output Format
严格以 JSON 格式返回：
{{
    "credibility_build": "信任建立方式描述",
    "pain_amplification": "痛点放大方式描述",
    "information_density_curve": [
        {{"segment": "段落描述", "density": "high/medium/low", "position": "开头/中段/结尾"}}
    ],
    "emotion_curve": [
        {{"emotion": "情绪名称", "trigger": "触发点描述"}}
    ],
    "cta_pattern": "CTA 收尾模式描述",
    "closing_emotion": "收尾情绪描述"
}}

# Self-Verification
1. 信息密度曲线至少标注 3 个段落
2. 情绪曲线至少包含 3 个情绪节点
3. CTA 模式必须具体，不能泛泛而谈
只有确认检查通过后，才返回最终 JSON。"""


def build_technique_driven_rewrite_prompt(
    source_text: str,
    hook_analysis: HookAnalysis,
    persona: PersonalityProfile,
    topic_technique: TopicTechnique | None = None,
    structure_map: ContentStructureMap | None = None,
    few_shot_examples: str | None = None,
) -> str:
    """构建「技法驱动 + 风格驱动」双轨重写 Prompt"""
    verbal_tics = persona.verbal_tics[:5]
    grammar_prefs = persona.grammar_prefs
    tempo = persona.temporal_patterns
    deep_psy = persona.deep_psychology

    # 钩子技法部分
    hook_section = f"""## 钩子技法
- 类型：{hook_analysis.hook_type.value}
- 公式：{hook_analysis.structural_formula}
- 心理机制：{hook_analysis.psychological_mechanism}
- 重建模板：{hook_analysis.reconstruction_template}"""

    # 选题技法部分
    topic_section = ""
    if topic_technique:
        topic_section = f"""
## 选题切入
- 角度偏好：{', '.join(topic_technique.angle_patterns[:3])}
- 痛点：{', '.join(topic_technique.pain_points[:3])}"""

    # 结构映射部分
    structure_section = ""
    if structure_map:
        structure_section = f"""
## 内容结构
- 信任建立：{structure_map.credibility_build}
- 痛点放大：{structure_map.pain_amplification}
- CTA 模式：{structure_map.cta_pattern}
- 收尾情绪：{structure_map.closing_emotion}"""

    # RAG few-shot 示例部分
    few_shot_section = ""
    if few_shot_examples:
        few_shot_section = f"""
## 真实语料参考（风格相似的真实文案）
{few_shot_examples}

请参考以上真实语料的风格和表达方式，但不要直接复制内容。"""

    return f"""# Role
你是一个短视频人格重构与内容技法专家。

# Task
根据以下技法约束和风格约束，重写原始素材。

{hook_section}
{topic_section}
{structure_section}
{few_shot_section}

## 风格约束
- 口头禅：{', '.join(verbal_tics) if verbal_tics else '无'}
- 语法偏好：{', '.join(grammar_prefs) if grammar_prefs else '短句为主'}
- 节奏：{tempo.speech_rhythm} (约每分钟 {tempo.pause_frequency} 次停顿)
- 情感基调：{deep_psy.emotional_tone}

# Source Material
{source_text}

# Output Format
严格以 JSON 格式返回：
{{
    "golden_hook": "重写后的黄金3秒开场（必须使用上述钩子技法）",
    "rewritten_body": "重写后的正文",
    "technique_applied": "简述应用了哪些技法",
    "style_notes": "风格说明"
}}

# Self-Verification
1. golden_hook 必须符合钩子技法的结构公式
2. 术语保护占位符【PROTECTED_TERM_n】必须原样保留
3. 风格约束必须体现在正文中
只有确认检查通过后，才返回最终 JSON。"""

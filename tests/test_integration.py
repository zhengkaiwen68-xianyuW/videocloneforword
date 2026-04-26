"""
集成测试

测试完整流程（使用 Mock LLM）：
1. 选题技法分析
2. 钩子拆解
3. 内容结构映射
4. 技法驱动重写
5. 评分

验证各模块之间的数据流转正确。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from persona_engine.core.types import (
    HookAnalysis,
    HookType,
    TopicTechnique,
    ContentStructureMap,
    PersonalityProfile,
    LogicArchitecture,
    TemporalPattern,
    DeepPsychology,
)
from persona_engine.technique.hook_deconstructor import HookDeconstructor
from persona_engine.technique.topic_analyzer import TopicAnalyzer
from persona_engine.technique.structure_mapper import StructureMapper
from persona_engine.technique.technique_repo import TechniqueKnowledgeBase
from persona_engine.technique.prompt_library import (
    build_topic_analysis_prompt,
    build_hook_deconstruct_prompt,
    build_structure_map_prompt,
    build_technique_driven_rewrite_prompt,
)


# ── Mock LLM Provider ──

class IntegrationMockLLM:
    """集成测试用的 Mock LLM，返回合理的结构化数据"""

    def __init__(self):
        self.call_count = 0

    async def generate(self, prompt, system_prompt=None, **kwargs):
        self.call_count += 1
        return "mock generated text"

    async def generate_json(self, prompt, system_prompt=None, **kwargs):
        self.call_count += 1

        # 根据 prompt 内容返回不同的结构化数据
        if "选题" in prompt or "角度偏好" in prompt:
            return {
                "angle_patterns": ["反常识切入", "痛点前置"],
                "pain_points": ["效率焦虑", "学习成本"],
                "topic_formulas": ["{常识} + 根本不是{常识}"],
                "selection_criteria": ["与效率相关"],
                "avoid_patterns": ["政治敏感"],
            }
        elif "钩子" in prompt or "Hook" in prompt:
            return {
                "hook_type": "reverse_logic",
                "psychological_mechanism": "认知失调",
                "structural_formula": "{常识} + 根本不是{常识}",
                "why_it_works": "打破固有认知",
                "reconstruction_template": "用'不用X'句式",
            }
        elif "结构" in prompt or "操控地图" in prompt:
            return {
                "credibility_build": "数据引用建立信任",
                "pain_amplification": "放大效率焦虑",
                "information_density_curve": [
                    {"segment": "开头", "density": "high", "position": "开头"},
                    {"segment": "中段", "density": "medium", "position": "中段"},
                    {"segment": "结尾", "density": "high", "position": "结尾"},
                ],
                "emotion_curve": [
                    {"emotion": "好奇", "trigger": "反常识开头"},
                    {"emotion": "焦虑", "trigger": "痛点放大"},
                    {"emotion": "释然", "trigger": "解决方案"},
                ],
                "cta_pattern": "引导关注",
                "closing_emotion": "紧迫感",
            }
        elif "重写" in prompt:
            return {
                "golden_hook": "你根本不用学Excel",
                "rewritten_body": "只需要掌握这3个函数就够了...",
                "technique_applied": "反逻辑钩子 + 痛点前置",
                "style_notes": "保持了原有人格风格",
            }
        else:
            return {"result": "mock"}


# ── Fixtures ──

@pytest.fixture
def mock_llm():
    return IntegrationMockLLM()


@pytest.fixture
def sample_persona():
    """测试用人格画像"""
    return PersonalityProfile(
        id="test_persona",
        name="测试博主",
        verbal_tics=["哎呀", "这个"],
        grammar_prefs=["短句为主", "口语化"],
        logic_architecture=LogicArchitecture(
            opening_style="反常识开场",
            transition_patterns=["但是", "其实"],
            closing_style="引导关注",
            topic_organization="线性叙述",
        ),
        temporal_patterns=TemporalPattern(
            avg_pause_duration=0.5,
            pause_frequency=5.0,
            speech_rhythm="medium",
            excitement_curve=[0.3, 0.7, 0.5],
        ),
        deep_psychology=DeepPsychology(
            emotional_tone="自信中立",
            emotional_arc=["好奇", "焦虑", "释然"],
            rhetorical_devices=["反问", "排比"],
            lexicon=["效率", "技巧", "方法"],
        ),
        source_asr_texts=[
            "Excel根本不用学，你只需要掌握这3个函数就能搞定90%的工作。",
            "月薪3000和30000的人，区别只有这一点，就是他们用Excel的方式不同。",
        ],
    )


# ── Integration Tests ──

class TestTopicAnalysisIntegration:
    """选题分析集成测试"""

    @pytest.mark.asyncio
    async def test_analyze_multiple_texts(self, mock_llm):
        """多文本选题分析"""
        analyzer = TopicAnalyzer(llm_provider=mock_llm)

        texts = [
            "Excel根本不用学，你只需要掌握这3个函数...",
            "月薪3000和30000的人，区别只有这一点...",
            "你还在用这种方法做PPT？太慢了！",
        ]

        result = await analyzer.analyze(texts)

        assert isinstance(result, TopicTechnique)
        assert len(result.angle_patterns) > 0
        assert len(result.pain_points) > 0
        assert len(result.topic_formulas) > 0


class TestHookDeconstructIntegration:
    """钩子拆解集成测试"""

    @pytest.mark.asyncio
    async def test_deconstruct_and_verify(self, mock_llm):
        """拆解并验证结果"""
        deconstructor = HookDeconstructor(llm_provider=mock_llm)

        hook_text = "Excel根本不用学"
        full_text = "Excel根本不用学，你只需要掌握这3个函数就能搞定90%的工作。"

        result = await deconstructor.deconstruct(
            hook_text=hook_text,
            full_text=full_text,
            source_video_url="https://bilibili.com/video/BV123",
            persona_id="test",
        )

        assert result.hook_type == HookType.REVERSE_LOGIC
        assert result.hook_text == hook_text
        assert result.structural_formula != ""

    @pytest.mark.asyncio
    async def test_batch_deconstruct(self, mock_llm):
        """批量拆解"""
        deconstructor = HookDeconstructor(llm_provider=mock_llm)

        hooks = [
            "Excel根本不用学",
            "你还在用这种方法？",
            "3秒搞定",
        ]

        results = await deconstructor.batch_deconstruct(hook_texts=hooks)
        assert len(results) == 3
        assert all(isinstance(r, HookAnalysis) for r in results)


class TestStructureMapIntegration:
    """内容结构映射集成测试"""

    @pytest.mark.asyncio
    async def test_map_structure(self, mock_llm):
        """映射内容结构"""
        mapper = StructureMapper(llm_provider=mock_llm)

        full_text = (
            "Excel根本不用学，你只需要掌握这3个函数就能搞定90%的工作。"
            "第一个函数是VLOOKUP，第二个是IF，第三个是SUM。"
            "学会这三个，你就是Excel高手了。关注我，教你更多技巧。"
        )

        result = await mapper.map_structure(
            full_text=full_text,
            source_video_url="https://bilibili.com/video/BV123",
            persona_id="test",
        )

        assert isinstance(result, ContentStructureMap)
        assert result.credibility_build != ""
        assert result.cta_pattern != ""
        assert len(result.emotion_curve) > 0


class TestFullPipelineIntegration:
    """完整流程集成测试"""

    @pytest.mark.asyncio
    async def test_full_analysis_pipeline(self, mock_llm, sample_persona):
        """完整分析流程：选题 → 钩子 → 结构 → 重写"""

        # Step 1: 选题分析
        topic_analyzer = TopicAnalyzer(llm_provider=mock_llm)
        topic_result = await topic_analyzer.analyze(sample_persona.source_asr_texts)
        assert isinstance(topic_result, TopicTechnique)

        # Step 2: 钩子拆解
        hook_deconstructor = HookDeconstructor(llm_provider=mock_llm)
        hooks = []
        for text in sample_persona.source_asr_texts:
            hook_text = HookDeconstructor.extract_hook_from_text(text)
            hook = await hook_deconstructor.deconstruct(
                hook_text=hook_text,
                full_text=text,
                persona_id=sample_persona.id,
            )
            hooks.append(hook)
        assert len(hooks) == 2

        # Step 3: 内容结构映射
        mapper = StructureMapper(llm_provider=mock_llm)
        structures = []
        for text in sample_persona.source_asr_texts:
            structure = await mapper.map_structure(
                full_text=text,
                hook_analysis=hooks[0],
                persona_id=sample_persona.id,
            )
            structures.append(structure)
        assert len(structures) == 2

        # Step 4: 生成技法驱动重写 Prompt
        prompt = build_technique_driven_rewrite_prompt(
            source_text="原始素材内容",
            hook_analysis=hooks[0],
            persona=sample_persona,
            topic_technique=topic_result,
            structure_map=structures[0],
        )
        assert "钩子技法" in prompt
        assert "风格约束" in prompt
        assert "reverse_logic" in prompt

        # Step 5: 验证数据流转
        assert hooks[0].hook_type == HookType.REVERSE_LOGIC
        assert topic_result.angle_patterns[0] == "反常识切入"
        assert structures[0].cta_pattern != ""


class TestPromptLibraryIntegration:
    """Prompt 模板库集成测试"""

    def test_topic_analysis_prompt(self):
        """选题分析 Prompt"""
        prompt = build_topic_analysis_prompt(["文本1", "文本2"])
        assert "视频 1" in prompt
        assert "视频 2" in prompt
        assert "角度偏好" in prompt

    def test_hook_deconstruct_prompt(self):
        """钩子拆解 Prompt"""
        prompt = build_hook_deconstruct_prompt("Excel不用学", "完整文本...")
        assert "Excel不用学" in prompt
        assert "完整文本" in prompt

    def test_structure_map_prompt(self):
        """结构映射 Prompt"""
        prompt = build_structure_map_prompt("完整文本", [{"time": "0:05", "text": "开头"}])
        assert "完整文本" in prompt
        assert "0:05" in prompt

    def test_technique_driven_rewrite_prompt(self, sample_persona):
        """技法驱动重写 Prompt"""
        hook = HookAnalysis(
            hook_text="测试",
            hook_type=HookType.REVERSE_LOGIC,
            psychological_mechanism="认知失调",
            structural_formula="{X}不用{Y}",
            why_it_works="打破认知",
            reconstruction_template="模板",
            source_video_url="",
            persona_id="",
        )
        topic = TopicTechnique(
            angle_patterns=["反常识"],
            pain_points=["焦虑"],
            topic_formulas=["公式"],
            selection_criteria=["标准"],
            avoid_patterns=["禁区"],
        )
        structure = ContentStructureMap(
            hook=hook,
            credibility_build="数据引用",
            pain_amplification="放大焦虑",
            information_density_curve=[],
            emotion_curve=[],
            cta_pattern="引导关注",
            closing_emotion="紧迫",
        )

        prompt = build_technique_driven_rewrite_prompt(
            source_text="原始素材",
            hook_analysis=hook,
            persona=sample_persona,
            topic_technique=topic,
            structure_map=structure,
        )

        assert "钩子技法" in prompt
        assert "选题切入" in prompt
        assert "内容结构" in prompt
        assert "风格约束" in prompt
        assert "反常识" in prompt

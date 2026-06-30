from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from core.suggestion import (
    SuggestionEngine,
    SuggestionResult,
    SuggestionDetail,
    apply_hard_filters,
)
from core.ai_router import RouterResult


# ══════════════════════════════════════════════════════════════════
# 共享 fixture
# ══════════════════════════════════════════════════════════════════

@pytest.fixture
def mock_router():
    """返回一个 MagicMock，其 chat 方法可被各测试按需配置"""
    return MagicMock()


@pytest.fixture
def engine_with_test_prompt(mock_router):
    """创建 SuggestionEngine 并注入 test system prompt，避免读真实文件"""
    engine = SuggestionEngine(router=mock_router)
    engine._system_prompt = "test system prompt"
    return engine


@pytest.fixture
def minimal_outfit_data():
    """与 outfit_parser.to_dict() 输出对齐的最简穿搭数据"""
    return {
        "outfit_description": "白T+牛仔裤",
        "overall_style": "休闲",
        "no_count": 1,
        "no_items": ["下装合身吗？"],
        "items": [
            {
                "category": "TS",
                "category_cn": "短袖T恤",
                "color": "白色",
                "secondary_color": "",
                "fit": "合身",
                "wearing_style": "常规",
                "notes": "",
            },
        ],
        "checklist": [
            {
                "id": "fit_bottom",
                "question": "下装合身吗？",
                "result": "NO",
                "reason": "裤长问题",
            },
        ],
    }


@pytest.fixture
def user_context():
    return {
        "body_shape": {
            "body_type": "梨形",
            "shoulder_hip_ratio": "肩窄胯宽",
            "leg_body_ratio": "腿偏短",
            "skin_tone": "暖白皮",
            "height": 170,
        },
        "skill_history": {
            "mastered": ["法式半塞", "颜色呼应"],
            "recent": [
                {"skill_name": "袖口翻折", "date": "2026-06-25"},
            ],
            "disliked": [],
        },
        "weather": {
            "condition": "晴天",
            "temperature": 28,
            "season": "夏季",
        },
    }


# ══════════════════════════════════════════════════════════════════
# 1. SuggestionResult 默认值
# ══════════════════════════════════════════════════════════════════

class TestSuggestionResultDefaults:
    """SuggestionResult / SuggestionDetail 数据类默认值验证"""

    def test_suggestion_result_default(self):
        """SuggestionResult() 默认值：success=False, scene="", suggestion=None"""
        result = SuggestionResult()
        assert result.success is False
        assert result.scene == ""
        assert result.suggestion is None

    def test_suggestion_result_with_detail(self):
        """创建带 SuggestionDetail 的 SuggestionResult，验证字段正确传递"""
        detail = SuggestionDetail(
            skill_id="cuff_roll",
            skill_name="裤脚卷边",
            headline="试试把裤脚往上卷一圈",
            why="裤长稍长会影响比例",
            how_to="向外翻折一次，约2-3cm",
            expected_effect="腿长视觉+10%",
            difficulty=1,
            estimated_time_seconds=10,
        )
        result = SuggestionResult(
            success=True,
            scene="微调",
            suggestion=detail,
            encouragement="今天颜色搭配不错！",
        )

        assert result.success is True
        assert result.scene == "微调"
        assert result.suggestion is detail
        assert result.suggestion.skill_id == "cuff_roll"
        assert result.suggestion.skill_name == "裤脚卷边"
        assert result.suggestion.headline == "试试把裤脚往上卷一圈"
        assert result.suggestion.difficulty == 1
        assert result.suggestion.estimated_time_seconds == 10
        assert result.encouragement == "今天颜色搭配不错！"


# ══════════════════════════════════════════════════════════════════
# 2. System Prompt 加载
# ══════════════════════════════════════════════════════════════════

class TestSystemPrompt:
    """SuggestionEngine.system_prompt 属性测试"""

    def test_system_prompt_loads(self, mock_router):
        """system_prompt 加载成功，长度 > 300，包含关键短语"""
        # 不设置 _system_prompt，让 property 真实加载 prompts/suggestion.md
        engine = SuggestionEngine(router=mock_router)
        prompt = engine.system_prompt

        assert len(prompt) > 300, f"prompt 长度 {len(prompt)} 应 > 300"
        assert "不否定" in prompt
        assert "具体到动作" in prompt


# ══════════════════════════════════════════════════════════════════
# 3. _build_user_message
# ══════════════════════════════════════════════════════════════════

class TestBuildUserMessage:
    """_build_user_message() 方法测试"""

    def test_build_user_message_basic(self, engine_with_test_prompt, minimal_outfit_data):
        """用最简 outfit_data 调用，消息包含 '整体描述' 和品类信息"""
        engine = engine_with_test_prompt
        msg = engine._build_user_message(minimal_outfit_data, {})

        assert "整体描述" in msg
        assert "白T+牛仔裤" in msg
        assert "短袖T恤" in msg
        assert "TS" in msg
        assert "下装合身吗？" in msg

    def test_build_user_message_empty_checklist(self, engine_with_test_prompt):
        """checklist 为空列表时不崩溃，no_count=0"""
        outfit_data = {
            "outfit_description": "测试",
            "overall_style": "",
            "no_count": 0,
            "no_items": [],
            "items": [],
            "checklist": [],  # 照片质量差时的降级输出
        }
        engine = engine_with_test_prompt
        msg = engine._build_user_message(outfit_data, {})
        assert "Checklist" in msg
        assert "❌ 数量：0" in msg

    def test_build_user_message_with_context(
        self, engine_with_test_prompt, minimal_outfit_data, user_context
    ):
        """传入 user_context，验证消息中包含身形、技巧、天气信息"""
        engine = engine_with_test_prompt
        msg = engine._build_user_message(minimal_outfit_data, user_context)

        # 身形
        assert "梨形" in msg
        assert "肩窄胯宽" in msg
        assert "170cm" in msg

        # 技巧历史
        assert "法式半塞" in msg
        assert "颜色呼应" in msg
        assert "袖口翻折" in msg

        # 天气
        assert "晴天" in msg
        assert "28°C" in msg
        assert "夏季" in msg


# ══════════════════════════════════════════════════════════════════
# 4. generate() 方法
# ══════════════════════════════════════════════════════════════════

class TestGenerate:
    """SuggestionEngine.generate() 方法测试"""

    def test_generate_vlm_failure(
        self, engine_with_test_prompt, minimal_outfit_data, mock_router
    ):
        """mock router.chat 返回 success=False → generate 返回 success=False"""
        mock_router.chat.return_value = RouterResult(
            success=False,
            error="模拟的 LLM 调用失败",
            model_used="test/model",
            provider_used="test",
            latency_ms=50,
        )

        result = engine_with_test_prompt.generate(minimal_outfit_data)
        assert result.success is False
        assert result.error == "模拟的 LLM 调用失败"
        assert result.model_used == "test/model"

    def test_generate_invalid_json(
        self, engine_with_test_prompt, minimal_outfit_data, mock_router
    ):
        """mock router.chat 返回非 JSON 文本 → generate 返回 success=False + error 含 'JSON'"""
        mock_router.chat.return_value = RouterResult(
            success=True,
            data="这是一个完全不是 JSON 的纯文本回复，没有任何花括号",
            model_used="test/model",
            provider_used="test",
            latency_ms=50,
        )

        result = engine_with_test_prompt.generate(minimal_outfit_data)
        assert result.success is False
        assert result.error is not None
        assert "JSON" in result.error

    def test_generate_success(
        self, engine_with_test_prompt, minimal_outfit_data, mock_router
    ):
        """mock router.chat 返回完整有效 JSON → 验证所有返回字段"""
        mock_router.chat.return_value = RouterResult(
            success=True,
            data=(
                '{"scene":"微调",'
                '"checklist_summary":{"yes_count":6,"no_items":["下装合身吗？"],"main_issue":"裤长问题"},'
                '"suggestion":{"skill_id":"cuff_roll","skill_name":"裤脚卷边","headline":"试试把裤脚往上卷一圈","why":"裤长稍长会影响比例","how_to":"向外翻折一次，约2-3cm","expected_effect":"腿长视觉+10%","difficulty":1,"estimated_time_seconds":10},'
                '"tone":"friendly",'
                '"encouragement":"今天颜色搭配不错！"}'
            ),
            model_used="test/model",
            provider_used="test",
            latency_ms=100,
        )

        result = engine_with_test_prompt.generate(minimal_outfit_data)

        assert result.success is True
        assert result.scene == "微调"
        assert result.suggestion is not None
        assert result.suggestion.skill_id == "cuff_roll"
        assert result.suggestion.headline != ""
        assert result.encouragement != ""
        assert result.model_used == "test/model"


# ══════════════════════════════════════════════════════════════════
# 5. apply_hard_filters 硬过滤规则
# ══════════════════════════════════════════════════════════════════

class TestHardFilters:
    """apply_hard_filters() 硬过滤规则测试"""

    def test_hard_filter_sleeve_roll_on_short_sleeve(self, minimal_outfit_data):
        """穿 TS（短袖）+ skill_id='sleeve_roll' → 返回 success=False"""
        # minimal_outfit_data 里有 category="TS" 的单品
        result = SuggestionResult(
            success=True,
            scene="微调",
            suggestion=SuggestionDetail(
                skill_id="sleeve_roll",
                skill_name="袖口翻折",
            ),
        )
        filtered = apply_hard_filters(result, minimal_outfit_data)
        assert filtered.success is False
        assert "[硬过滤]" in filtered.error

    def test_hard_filter_cuff_roll_on_shorts(self):
        """穿 SHORTS（短裤）+ skill_id='cuff_roll' → 返回 success=False"""
        outfit_with_shorts = {
            "items": [
                {"category": "SHORTS", "category_cn": "短裤"},
            ],
        }
        result = SuggestionResult(
            success=True,
            scene="微调",
            suggestion=SuggestionDetail(
                skill_id="cuff_roll",
                skill_name="裤脚卷边",
            ),
        )
        filtered = apply_hard_filters(result, outfit_with_shorts)
        assert filtered.success is False
        assert "[硬过滤]" in filtered.error

    def test_hard_filter_passes_valid_combo(self):
        """穿 JEANS（长裤）+ skill_id='cuff_roll' → 不过滤，success=True"""
        outfit_with_jeans = {
            "items": [
                {"category": "JEANS", "category_cn": "牛仔裤"},
            ],
        }
        result = SuggestionResult(
            success=True,
            scene="微调",
            suggestion=SuggestionDetail(
                skill_id="cuff_roll",
                skill_name="裤脚卷边",
            ),
        )
        filtered = apply_hard_filters(result, outfit_with_jeans)
        assert filtered.success is True
        assert filtered.error is None

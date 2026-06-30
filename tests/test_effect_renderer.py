from __future__ import annotations

import tempfile
import pytest
from unittest.mock import MagicMock

from core.effect_renderer import EffectRenderer, EffectRendererResult
from core.ai_router import RouterResult


# ══════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════

@pytest.fixture
def mock_router():
    return MagicMock()


@pytest.fixture
def renderer(mock_router):
    return EffectRenderer(router=mock_router)


@pytest.fixture
def tmp_photo():
    with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
        yield f.name


@pytest.fixture
def outfit_data():
    return {
        "outfit_description": "白T+牛仔裤",
        "items": [
            {
                "category": "TS", "category_cn": "短袖T恤",
                "color": "白色", "secondary_color": "",
                "fit": "宽松", "wearing_style": "常规",
                "notes": "纯棉面料",
            },
            {
                "category": "JEANS", "category_cn": "牛仔裤",
                "color": "深蓝色", "secondary_color": "",
                "fit": "直筒", "wearing_style": "常规穿着",
                "notes": "",
            },
        ],
    }


@pytest.fixture
def suggestion():
    return {
        "skill_id": "french_tuck",
        "skill_name": "法式半塞",
        "headline": "试试把T恤前摆塞进裤腰一点点",
        "why": "衣长偏长会显腿短",
        "how_to": "捏住T恤前摆中间一小块，塞进裤腰约3-4cm",
        "expected_effect": "腿长视觉+10%",
        "difficulty": 1,
        "estimated_time_seconds": 5,
    }


@pytest.fixture
def user_context():
    return {
        "body_shape": {
            "body_type": "梨形",
            "height": 170,
        },
    }


# ══════════════════════════════════════════════════════════════════
# 1. EffectRendererResult 默认值
# ══════════════════════════════════════════════════════════════════

def test_result_defaults():
    """EffectRendererResult 默认值：success=False, 空列表"""
    r = EffectRendererResult()
    assert r.success is False
    assert r.image_urls == []
    assert r.prompt_used == ""
    assert r.error is None


# ══════════════════════════════════════════════════════════════════
# 2. _build_prompt 基础测试
# ══════════════════════════════════════════════════════════════════

class TestBuildPrompt:
    """_build_prompt() 方法测试"""

    def test_prompt_contains_outfit_items(self, renderer, outfit_data, suggestion, user_context):
        """prompt 包含颜色+品类描述"""
        prompt = renderer._build_prompt(outfit_data, suggestion, user_context)
        assert "白色" in prompt
        assert "短袖T恤" in prompt
        assert "深蓝色" in prompt
        assert "牛仔裤" in prompt

    def test_prompt_contains_change(self, renderer, outfit_data, suggestion, user_context):
        """prompt 包含调整动作描述"""
        prompt = renderer._build_prompt(outfit_data, suggestion, user_context)
        assert "French Tuck" in prompt
        assert "tucked into the waistband" in prompt

    def test_prompt_contains_style_constraints(self, renderer, outfit_data, suggestion, user_context):
        """prompt 包含风格约束"""
        prompt = renderer._build_prompt(outfit_data, suggestion, user_context)
        assert "photorealistic" in prompt.lower()
        assert "full body" in prompt.lower()

    def test_prompt_contains_body_info(self, renderer, outfit_data, suggestion, user_context):
        """prompt 包含身形信息"""
        prompt = renderer._build_prompt(outfit_data, suggestion, user_context)
        assert "梨形" in prompt
        assert "170cm" in prompt

    def test_prompt_without_body_context(self, renderer, outfit_data, suggestion):
        """user_context 为空时不崩溃"""
        prompt = renderer._build_prompt(outfit_data, suggestion, {})
        assert len(prompt) > 100
        assert "梨形" not in prompt

    def test_prompt_filters_regular_wearing_style(self, renderer, outfit_data, suggestion, user_context):
        """'常规' 和 '常规穿着' 不出现在穿著方式描述中"""
        prompt = renderer._build_prompt(outfit_data, suggestion, user_context)
        # outfit_data 中两个 item 的 wearing_style 分别为 "常规" 和 "常规穿着"，都应被过滤
        assert "Currently styled with" not in prompt

    def test_prompt_keeps_non_regular_wearing_style(self, renderer, suggestion, user_context):
        """非'常规'的穿着方式应保留"""
        outfit_with_style = {
            "items": [
                {"category": "TS", "category_cn": "短袖T恤", "color": "白色",
                 "secondary_color": "", "fit": "宽松",
                 "wearing_style": "袖口卷起两圈", "notes": ""},
            ],
        }
        prompt = renderer._build_prompt(outfit_with_style, suggestion, user_context)
        assert "袖口卷起两圈" in prompt

    def test_prompt_with_empty_items(self, renderer, suggestion, user_context):
        """items 为空时用 outfit_description 兜底"""
        outfit_empty = {"outfit_description": "黑色连衣裙", "items": []}
        prompt = renderer._build_prompt(outfit_empty, suggestion, user_context)
        assert "黑色连衣裙" in prompt

    def test_prompt_color_pop_skill(self, renderer, outfit_data, user_context):
        """小面积亮色点缀：prompt 包含 accent color"""
        color_sugg = {"skill_name": "小面积亮色点缀", "how_to": "加亮色配饰"}
        prompt = renderer._build_prompt(outfit_data, color_sugg, user_context)
        assert "accent" in prompt.lower()

    def test_prompt_unknown_skill_falls_back_to_how_to(self, renderer, outfit_data, user_context):
        """未知技巧：用 how_to 原文"""
        unknown_sugg = {"skill_name": "未知技巧XYZ", "how_to": "把左袖往上拉3厘米"}
        prompt = renderer._build_prompt(outfit_data, unknown_sugg, user_context)
        assert "把左袖往上拉3厘米" in prompt


# ══════════════════════════════════════════════════════════════════
# 3. render() 方法
# ══════════════════════════════════════════════════════════════════

class TestRender:
    """EffectRenderer.render() 方法测试"""

    def test_render_empty_suggestion(self, renderer, outfit_data, tmp_photo):
        """suggestion 为空 → success=False"""
        result = renderer.render(outfit_data, {}, tmp_photo)
        assert result.success is False
        assert result.error is not None
        assert "skill_name" in result.error

    def test_render_photo_not_found(self, renderer, outfit_data, suggestion):
        """照片不存在 → success=False"""
        result = renderer.render(outfit_data, suggestion, "/nonexistent/photo.jpg")
        assert result.success is False
        assert "不存在" in result.error

    def test_render_seedream_fails(self, renderer, outfit_data, suggestion, tmp_photo, mock_router):
        """router.generate_image 返回 success=False"""
        mock_router.generate_image.return_value = RouterResult(
            success=False,
            error="Seedream API 500",
            model_used="volcengine/seedream-5.0",
        )
        result = renderer.render(outfit_data, suggestion, tmp_photo)
        assert result.success is False
        assert "Seedream" in result.error

    def test_render_success(self, renderer, outfit_data, suggestion, tmp_photo, mock_router):
        """正常生图成功路径"""
        mock_router.generate_image.return_value = RouterResult(
            success=True,
            data={
                "data": [
                    {"url": "https://example.com/effect1.jpg"},
                ],
            },
            model_used="volcengine/seedream-5.0",
            provider_used="volcengine",
            latency_ms=5000,
        )
        result = renderer.render(outfit_data, suggestion, tmp_photo)
        assert result.success is True
        assert len(result.image_urls) == 1
        assert "https://example.com/effect1.jpg" in result.image_urls
        assert len(result.prompt_used) > 0
        assert result.model_used == "volcengine/seedream-5.0"


# ══════════════════════════════════════════════════════════════════
# 4. _extract_urls 边界
# ══════════════════════════════════════════════════════════════════

def test_extract_urls_empty():
    """空数据 → 空列表"""
    assert EffectRenderer._extract_urls({}) == []
    assert EffectRenderer._extract_urls(None) == []


def test_extract_urls_missing_url():
    """data 中有对象但无 url"""
    data = {"data": [{"url": ""}, {"other": "field"}]}
    urls = EffectRenderer._extract_urls(data)
    assert urls == []

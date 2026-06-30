"""测试主编排器 run_pipeline()"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from core.pipeline import run_pipeline


# ══════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════

@pytest.fixture
def mock_outfit_result():
    """模拟段一成功结果"""
    mock = MagicMock()
    mock.success = True
    mock.outfit_description = "白T恤配牛仔裤"
    mock.overall_style = "休闲简约"
    mock.photo_quality = "good"
    mock.photo_quality_note = ""
    mock.no_count = 1
    mock.no_items = ["上下身比例舒服吗？"]
    mock.latency_ms = 5000.0
    mock.error = None
    mock.items = [
        MagicMock(category="TS", category_cn="短袖T恤", color="白色",
                   secondary_color="", fit="宽松", wearing_style="常规", notes=""),
        MagicMock(category="JEANS", category_cn="牛仔裤", color="深蓝色",
                   secondary_color="", fit="直筒", wearing_style="常规穿着", notes=""),
    ]
    mock.checklist = [
        MagicMock(id="fit_top", question="上装合身吗？", result="YES", reason=""),
        MagicMock(id="prop_balance", question="上下身比例舒服吗？", result="NO", reason="T恤太长压腿长"),
    ]
    return mock


@pytest.fixture
def mock_suggestion_result():
    """模拟段二成功结果"""
    from core.suggestion import SuggestionResult, SuggestionDetail
    return SuggestionResult(
        success=True,
        scene="微调",
        suggestion=SuggestionDetail(
            skill_id="french_tuck",
            skill_name="法式半塞",
            headline="试试法式半塞",
            why="明确腰线显腿长",
            how_to="只塞正前方一小块",
            expected_effect="腿长+10%",
            difficulty=1,
            estimated_time_seconds=10,
        ),
        encouragement="今天颜色搭配不错",
        model_used="test-model",
        latency_ms=3000.0,
    )


@pytest.fixture
def mock_effect_result():
    """模拟段三成功结果"""
    from core.effect_renderer import EffectRendererResult
    return EffectRendererResult(
        success=True,
        image_urls=["https://example.com/effect1.png"],
        prompt_used="test prompt",
        model_used="seedream-test",
        latency_ms=15000.0,
    )


@pytest.fixture
def user_context():
    return {
        "user_id": "test_user",
        "body_shape": {"body_type": "梨形", "height": 170},
        "skill_history": {"mastered": [], "recent": [], "disliked": []},
    }


# ══════════════════════════════════════════════════════════════════
# 段一失败
# ══════════════════════════════════════════════════════════════════

@patch("core.pipeline.OutfitParser")
def test_pipeline_stage1_failure(mock_parser_cls, tmp_path, user_context):
    """段一失败 → 提前返回，不执行段二三"""
    mock_parser = MagicMock()
    mock_parser.parse.return_value.success = False
    mock_parser.parse.return_value.error = "VLM 调用失败"
    mock_parser_cls.return_value = mock_parser

    photo = tmp_path / "test.jpg"
    photo.write_text("fake")

    result = run_pipeline(str(photo), user_context)
    assert result["success"] is False
    assert "段一失败" in result["error"]
    assert result["outfit"] is None
    assert result["suggestion"] is None


# ══════════════════════════════════════════════════════════════════
# skip_suggestion 标志
# ══════════════════════════════════════════════════════════════════

@patch("core.pipeline.OutfitParser")
def test_pipeline_skip_suggestion(mock_parser_cls, mock_outfit_result, tmp_path, user_context):
    """skip_suggestion=True → 只执行段一，返回穿搭解析"""
    mock_parser = MagicMock()
    mock_parser.parse.return_value = mock_outfit_result
    mock_parser_cls.return_value = mock_parser

    photo = tmp_path / "test.jpg"
    photo.write_text("fake")

    result = run_pipeline(str(photo), user_context, skip_suggestion=True)
    assert result["success"] is True
    assert result["outfit"] is not None
    assert result["suggestion"] is None
    assert result["effect_image"] is None


# ══════════════════════════════════════════════════════════════════
# 段二降级（非阻塞）
# ══════════════════════════════════════════════════════════════════

@patch("core.pipeline.SuggestionEngine")
@patch("core.pipeline.OutfitParser")
def test_pipeline_stage2_degraded(mock_parser_cls, mock_engine_cls,
                                   mock_outfit_result, tmp_path, user_context):
    """段二失败 → 记录 fallback，不阻断整体成功"""
    mock_parser = MagicMock()
    mock_parser.parse.return_value = mock_outfit_result
    mock_parser_cls.return_value = mock_parser

    mock_engine = MagicMock()
    mock_engine.generate.return_value.success = False
    mock_engine.generate.return_value.error = "LLM 超时"
    mock_engine_cls.return_value = mock_engine

    photo = tmp_path / "test.jpg"
    photo.write_text("fake")

    result = run_pipeline(str(photo), user_context)
    assert result["success"] is True
    assert result["outfit"] is not None
    assert result["suggestion"]["fallback"] is True
    assert result["suggestion"]["error"] == "LLM 超时"
    assert result["effect_image"] is None  # 段二失败跳过段三


# ══════════════════════════════════════════════════════════════════
# 段三降级（非阻塞）
# ══════════════════════════════════════════════════════════════════

@patch("core.pipeline.EffectRenderer")
@patch("core.pipeline.SuggestionEngine")
@patch("core.pipeline.OutfitParser")
def test_pipeline_stage3_degraded(mock_parser_cls, mock_engine_cls, mock_renderer_cls,
                                   mock_outfit_result, mock_suggestion_result,
                                   tmp_path, user_context):
    """段三失败 → 记录 fallback，不阻断整体成功"""
    mock_parser = MagicMock()
    mock_parser.parse.return_value = mock_outfit_result
    mock_parser_cls.return_value = mock_parser

    mock_engine = MagicMock()
    mock_engine.generate.return_value = mock_suggestion_result
    mock_engine_cls.return_value = mock_engine

    mock_renderer = MagicMock()
    mock_renderer.render.return_value.success = False
    mock_renderer.render.return_value.error = "Seedream 生成失败"
    mock_renderer_cls.return_value = mock_renderer

    photo = tmp_path / "test.jpg"
    photo.write_text("fake")

    result = run_pipeline(str(photo), user_context)
    assert result["success"] is True
    assert result["outfit"] is not None
    assert result["suggestion"]["skill_id"] == "french_tuck"
    assert result["effect_image"]["fallback"] is True


# ══════════════════════════════════════════════════════════════════
# session_id
# ══════════════════════════════════════════════════════════════════

@patch("core.pipeline.OutfitParser")
def test_pipeline_generates_session_id(mock_parser_cls, tmp_path, user_context):
    """每次调用生成唯一 session_id"""
    mock_parser = MagicMock()
    mock_parser.parse.return_value.success = False
    mock_parser.parse.return_value.error = "fail"
    mock_parser_cls.return_value = mock_parser

    photo = tmp_path / "test.jpg"
    photo.write_text("fake")

    r1 = run_pipeline(str(photo), user_context)
    r2 = run_pipeline(str(photo), user_context)
    assert r1["session_id"] != r2["session_id"]
    assert len(r1["session_id"]) == 36  # UUID4 格式


# ══════════════════════════════════════════════════════════════════
# timeout 参数
# ══════════════════════════════════════════════════════════════════

@patch("core.pipeline.OutfitParser")
def test_pipeline_timeout_parameter(mock_parser_cls, mock_outfit_result, tmp_path, user_context):
    """timeout 参数被接受（实际超时在 router 层实现）"""
    mock_parser = MagicMock()
    mock_parser.parse.return_value = mock_outfit_result
    mock_parser_cls.return_value = mock_parser

    photo = tmp_path / "test.jpg"
    photo.write_text("fake")

    result = run_pipeline(str(photo), user_context, skip_suggestion=True, timeout=15.0)
    assert result["success"] is True
    assert result["total_latency_ms"] >= 0


# ══════════════════════════════════════════════════════════════════
# 空 user_context
# ══════════════════════════════════════════════════════════════════

@patch("core.pipeline.OutfitParser")
def test_pipeline_no_user_context(mock_parser_cls, tmp_path):
    """无 user_context → 正常降级为空 dict"""
    mock_parser = MagicMock()
    mock_parser.parse.return_value.success = False
    mock_parser.parse.return_value.error = "fail"
    mock_parser_cls.return_value = mock_parser

    photo = tmp_path / "test.jpg"
    photo.write_text("fake")

    result = run_pipeline(str(photo))  # 不传 user_context
    assert "session_id" in result

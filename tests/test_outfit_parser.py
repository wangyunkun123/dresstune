from __future__ import annotations

import tempfile
import pytest
from unittest.mock import MagicMock

from core.outfit_parser import (
    OutfitParser,
    OutfitResult,
    OutfitItem,
    ChecklistItem,
)
from core.ai_router import RouterResult


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def mock_router():
    """返回一个 MagicMock，其 chat 方法可被各测试按需配置"""
    return MagicMock()


@pytest.fixture
def parser_with_test_prompt(mock_router):
    """创建 OutfitParser 并注入 test prompt，避免读真实文件"""
    parser = OutfitParser()
    parser._system_prompt = "test system prompt"
    parser._router = mock_router
    return parser


@pytest.fixture
def success_response():
    """VLM 成功返回的标准 JSON（与真实 MiniMax-M3 输出格式一致）"""
    return RouterResult(
        success=True,
        data=(
            '{"outfit_description":"白色T恤配蓝色牛仔裤",'
            '"items":['
            '{"category":"TS","category_cn":"短袖T恤","color":"白色","secondary_color":"","fit":"合身","wearing_style":"常规","notes":"纯棉"},'
            '{"category":"JEANS","category_cn":"牛仔裤","color":"蓝色","secondary_color":"","fit":"宽松","wearing_style":"裤脚卷起一圈","notes":""}'
            '],'
            '"checklist":['
            '{"id":"fit_top","question":"上装合身吗？","result":"YES","reason":"OK"},'
            '{"id":"fit_bottom","question":"下装合身吗？","result":"NO","reason":"裤长问题"}'
            '],'
            '"overall_style":"休闲",'
            '"photo_quality":"good",'
            '"photo_quality_note":""'
            '}'
        ),
        model_used="test/model",
        provider_used="test",
        latency_ms=200,
    )


@pytest.fixture
def tmp_photo():
    """创建临时 jpg 文件，绕过文件存在检查"""
    with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
        yield f.name


# ═══════════════════════════════════════════════════════════════════
# Test 1: no_count / no_items — 全部 YES
# ═══════════════════════════════════════════════════════════════════

def test_no_count_all_yes():
    """Checklist 全部 YES 时 no_count=0, no_items=[]"""
    result = OutfitResult(
        success=True,
        checklist=[
            ChecklistItem(id="fit_top", question="上装合身吗？", result="YES", reason="合身"),
            ChecklistItem(id="fit_bottom", question="下装合身吗？", result="YES", reason="合身"),
            ChecklistItem(id="shoes", question="鞋合适吗？", result="YES", reason="合适"),
        ],
    )
    assert result.no_count == 0
    assert result.no_items == []


# ═══════════════════════════════════════════════════════════════════
# Test 2: no_count / no_items — 混合 YES/NO
# ═══════════════════════════════════════════════════════════════════

def test_no_count_mixed():
    """混合 YES/NO 时 no_count 正确计数，no_items 正确列表"""
    result = OutfitResult(
        success=True,
        checklist=[
            ChecklistItem(id="fit_top", question="上装合身吗？", result="YES", reason="OK"),
            ChecklistItem(id="fit_bottom", question="下装合身吗？", result="NO", reason="太长"),
            ChecklistItem(id="shoes", question="鞋搭吗？", result="YES", reason="OK"),
            ChecklistItem(id="color", question="颜色协调吗？", result="NO", reason="不搭"),
        ],
    )
    assert result.no_count == 2
    assert result.no_items == ["下装合身吗？", "颜色协调吗？"]


# ═══════════════════════════════════════════════════════════════════
# Test 3: system_prompt 懒加载
# ═══════════════════════════════════════════════════════════════════

def test_system_prompt_loads():
    """OutfitParser.system_prompt 加载成功，长度 > 500，包含关键内容"""
    parser = OutfitParser()
    prompt = parser.system_prompt
    assert len(prompt) > 500
    assert "品类代码" in prompt
    assert "checklist" in prompt


# ═══════════════════════════════════════════════════════════════════
# Test 4: 照片文件不存在
# ═══════════════════════════════════════════════════════════════════

def test_parse_file_not_found():
    """照片路径不存在时返回 success=False，error 包含 '不存在'"""
    parser = OutfitParser()
    result = parser.parse("/nonexistent/path/definitely_not_here.jpg")
    assert result.success is False
    assert result.error is not None
    assert "不存在" in result.error


# ═══════════════════════════════════════════════════════════════════
# Test 5: VLM 调用失败
# ═══════════════════════════════════════════════════════════════════

def test_parse_vlm_fails(parser_with_test_prompt, tmp_photo, mock_router):
    """mock router.chat 返回 success=False 时，parse 返回 success=False + 错误信息"""
    mock_router.chat.return_value = RouterResult(
        success=False,
        error="API 调用超时",
        model_used="test/model",
        provider_used="test",
        latency_ms=5000,
    )

    result = parser_with_test_prompt.parse(tmp_photo)

    assert result.success is False
    assert result.error is not None
    assert "VLM 调用失败" in result.error


# ═══════════════════════════════════════════════════════════════════
# Test 6: 解析成功路径
# ═══════════════════════════════════════════════════════════════════

def test_parse_success_path(parser_with_test_prompt, success_response, tmp_photo, mock_router):
    """mock router.chat 返回完整有效 JSON，验证解析结果各项字段"""
    mock_router.chat.return_value = success_response

    result = parser_with_test_prompt.parse(tmp_photo)

    assert result.success is True
    assert len(result.items) == 2
    assert result.items[0].category == "TS"
    assert result.items[1].category == "JEANS"
    assert result.overall_style == "休闲"
    assert result.outfit_description == "白色T恤配蓝色牛仔裤"
    assert result.no_count == 1
    assert result.no_items == ["下装合身吗？"]
    assert result.model_used == "test/model"
    assert result.photo_quality == "good"


# ═══════════════════════════════════════════════════════════════════
# Test 7: to_dict 静态方法
# ═══════════════════════════════════════════════════════════════════

def test_to_dict_static_method():
    """OutfitParser.to_dict() 返回正确 dict，包含所有关键字段"""
    result = OutfitResult(
        success=True,
        outfit_description="白色T恤配蓝色牛仔裤",
        items=[
            OutfitItem(
                category="TS",
                category_cn="短袖T恤",
                color="白色",
                secondary_color="",
                fit="合身",
                wearing_style="常规",
                notes="纯棉",
            ),
            OutfitItem(
                category="JEANS",
                category_cn="牛仔裤",
                color="蓝色",
                secondary_color="",
                fit="宽松",
                wearing_style="裤脚卷起一圈",
                notes="",
            ),
        ],
        checklist=[
            ChecklistItem(id="fit_top", question="上装合身吗？", result="YES", reason="OK"),
            ChecklistItem(id="fit_bottom", question="下装合身吗？", result="NO", reason="裤长问题"),
        ],
        overall_style="休闲",
        photo_quality="good",
        photo_quality_note="",
        raw_response='{"outfit_description":"...","items":[...]}',
        model_used="test/model",
        latency_ms=200,
    )

    d = OutfitParser.to_dict(result)

    assert isinstance(d, dict)
    assert d["outfit_description"] == "白色T恤配蓝色牛仔裤"
    assert d["overall_style"] == "休闲"
    assert d["success"] is True
    assert len(d["items"]) == 2
    assert d["items"][0]["category"] == "TS"
    assert d["items"][0]["color"] == "白色"
    assert len(d["checklist"]) == 2
    assert d["checklist"][0]["result"] == "YES"
    assert d["no_count"] == 1
    assert d["no_items"] == ["下装合身吗？"]

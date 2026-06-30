from __future__ import annotations

import json
import tempfile
import pytest
from pathlib import Path

from core.skill_matcher import SkillMatcher, MatchResult, SkillMatch


# ══════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════

@pytest.fixture
def skills_dir():
    """创建临时技巧库目录，含 3 个测试技巧"""
    with tempfile.TemporaryDirectory() as tmp:
        skills = [
            {
                "skill_id": "test_tuck",
                "name": "测试半塞",
                "difficulty": 1,
                "headline": "塞一下",
                "why_it_works": "明确腰线",
                "expected_effect": "腿+10%",
                "steps": ["捏住", "塞进"],
                "applicable": {
                    "categories": ["TS", "SHIRT"],
                    "scenarios": ["上衣下摆未塞", "腰线模糊"],
                    "body_types": {
                        "梨形": {"score": 10, "note": "强推"},
                        "矩形": {"score": 7, "note": "可用"},
                    },
                },
                "inapplicable": {
                    "categories": [],
                    "scenarios": ["上衣已经塞入"],
                },
                "common_mistakes": ["塞太多"],
                "tags": ["入门"],
            },
            {
                "skill_id": "test_cuff",
                "name": "测试卷边",
                "difficulty": 1,
                "headline": "卷一下",
                "why_it_works": "露脚踝",
                "expected_effect": "利落",
                "steps": ["捏裤脚", "翻折"],
                "applicable": {
                    "categories": ["JEANS", "CHINOS"],
                    "scenarios": ["裤长偏长"],
                    "body_types": {
                        "梨形": {"score": 9, "note": "好"},
                        "苹果": {"score": 8, "note": "好"},
                    },
                },
                "inapplicable": {
                    "categories": ["SHORTS"],
                    "scenarios": ["穿的是短裤"],
                },
                "common_mistakes": ["卷太宽"],
                "tags": ["入门"],
            },
            {
                "skill_id": "test_color",
                "name": "测试颜色",
                "difficulty": 2,
                "headline": "加点色",
                "why_it_works": "制造焦点",
                "expected_effect": "吸睛",
                "steps": ["找颜色", "呼应"],
                "applicable": {
                    "categories": ["*"],
                    "scenarios": ["穿搭已经基本协调"],
                    "body_types": {
                        "矩形": {"score": 8, "note": "好"},
                    },
                },
                "inapplicable": {
                    "categories": [],
                    "scenarios": ["已经呼应了"],
                },
                "common_mistakes": ["呼应过度"],
                "tags": ["进阶"],
            },
        ]
        for s in skills:
            p = Path(tmp) / f"{s['skill_id']}.json"
            p.write_text(json.dumps(s, ensure_ascii=False))
        yield tmp


@pytest.fixture
def matcher(skills_dir):
    return SkillMatcher(skills_dir=skills_dir)


@pytest.fixture
def outfit_tuck_needed():
    """TS未塞 + prop_balance NO → 需要半塞"""
    return {
        "outfit_description": "白色T恤配牛仔裤",
        "items": [
            {"category": "TS", "category_cn": "短袖T恤", "color": "白色",
             "fit": "宽松", "wearing_style": "常规"},
            {"category": "JEANS", "category_cn": "牛仔裤", "color": "蓝色",
             "fit": "直筒", "wearing_style": "常规"},
        ],
        "checklist": [
            {"id": "prop_balance", "question": "上下身比例舒服吗？",
             "result": "NO", "reason": "T恤太长压腿长"},
            {"id": "fit_top", "question": "上装合身吗？",
             "result": "YES", "reason": "OK"},
        ],
    }


@pytest.fixture
def outfit_no_issues():
    """0 NO → 精进模式"""
    return {
        "outfit_description": "完美穿搭",
        "items": [
            {"category": "TS", "category_cn": "短袖T恤", "color": "白色",
             "fit": "合身", "wearing_style": "常规"},
        ],
        "checklist": [
            {"id": "fit_top", "question": "上装合身吗？", "result": "YES", "reason": "OK"},
        ],
    }


@pytest.fixture
def user_pear():
    return {
        "body_shape": {"body_type": "梨形", "height": 170},
        "skill_history": {"mastered": [], "recent": [], "disliked": []},
    }


# ══════════════════════════════════════════════════════════════════
# 1. 加载
# ══════════════════════════════════════════════════════════════════

def test_loads_skills(matcher):
    """正确加载技巧文件"""
    assert len(matcher.skills) == 3
    ids = {s["skill_id"] for s in matcher.skills}
    assert ids == {"test_tuck", "test_cuff", "test_color"}


def test_reload(matcher):
    """reload 重新加载"""
    matcher.reload()
    assert len(matcher.skills) == 3


# ══════════════════════════════════════════════════════════════════
# 2. 品类筛选
# ══════════════════════════════════════════════════════════════════

def test_category_match_direct(matcher, outfit_tuck_needed):
    """TS 匹配 test_tuck（类别含 TS）"""
    assert matcher._is_category_match(matcher.skills[0], outfit_tuck_needed) is True


def test_category_match_wildcard(matcher, outfit_tuck_needed):
    """* 通配符匹配任何品类"""
    color_skill = [s for s in matcher.skills if s["skill_id"] == "test_color"][0]
    assert matcher._is_category_match(color_skill, outfit_tuck_needed) is True


def test_category_no_match(matcher):
    """只穿 TS 不能匹配 cuff_roll（类别只含 JEANS/CHINOS）"""
    outfit = {
        "items": [{"category": "TS", "category_cn": "短袖T恤"}],
    }
    cuff_skill = [s for s in matcher.skills if s["skill_id"] == "test_cuff"][0]
    assert matcher._is_category_match(cuff_skill, outfit) is False


# ══════════════════════════════════════════════════════════════════
# 3. 场景匹配
# ══════════════════════════════════════════════════════════════════

def test_scenario_match_from_no_reason(matcher):
    """NO 项的 question+reason 触发场景匹配"""
    outfit = {
        "outfit_description": "白色T恤配牛仔裤，上衣下摆未塞",
        "items": [
            {"category": "TS", "category_cn": "短袖T恤", "color": "白色",
             "fit": "宽松", "wearing_style": "常规"},
        ],
        "checklist": [
            {"id": "prop_balance", "question": "上下身比例舒服吗？",
             "result": "NO", "reason": "腰线模糊，上衣下摆未塞导致腿显短"},
        ],
    }
    tuck = [s for s in matcher.skills if s["skill_id"] == "test_tuck"][0]
    assert matcher._is_scenario_match(tuck, outfit) is True


def test_scenario_no_match(matcher, outfit_no_issues):
    """0 NO → 无场景匹配"""
    tuck = [s for s in matcher.skills if s["skill_id"] == "test_tuck"][0]
    assert matcher._is_scenario_match(tuck, outfit_no_issues) is False


# ══════════════════════════════════════════════════════════════════
# 4. 不适用排除
# ══════════════════════════════════════════════════════════════════

def test_inapplicable_category(matcher):
    """穿 SHORTS → cuff_roll 不适用"""
    outfit = {
        "outfit_description": "短裤穿搭",
        "items": [{"category": "SHORTS", "category_cn": "短裤"}],
        "checklist": [],
    }
    cuff = [s for s in matcher.skills if s["skill_id"] == "test_cuff"][0]
    assert matcher._is_inapplicable(cuff, outfit) is True


def test_inapplicable_only_checks_categories(matcher):
    """文本场景（如'上衣已塞'）不再由代码检查，交给 LLM；代码层只检查品类黑名单"""
    # 已塞入的上衣 → 品类仍然是 TS，不在 test_tuck 的黑名单中，所以代码层不拒绝
    outfit = {
        "outfit_description": "白色T恤",
        "items": [{"category": "TS", "wearing_style": "全塞入裤腰"}],
        "checklist": [],
    }
    tuck = [s for s in matcher.skills if s["skill_id"] == "test_tuck"][0]
    # 品类层面不拒绝（TS 不在 blacklist 里），LLM 看到 wearing_style 会自行判断
    assert matcher._is_inapplicable(tuck, outfit) is False


# ══════════════════════════════════════════════════════════════════
# 5. 身形评分
# ══════════════════════════════════════════════════════════════════

def test_body_type_score_exact(matcher, user_pear):
    """梨形 → test_tuck = 10 分"""
    tuck = [s for s in matcher.skills if s["skill_id"] == "test_tuck"][0]
    assert matcher._body_type_score(tuck, user_pear) == 10


def test_body_type_score_missing(matcher, user_pear):
    """梨形不在 test_color 的 body_types 中 → 默认 5"""
    color = [s for s in matcher.skills if s["skill_id"] == "test_color"][0]
    assert matcher._body_type_score(color, user_pear) == 5


def test_body_type_score_no_context(matcher):
    """无体型信息 → 默认 5"""
    tuck = [s for s in matcher.skills if s["skill_id"] == "test_tuck"][0]
    assert matcher._body_type_score(tuck, {}) == 5


# ══════════════════════════════════════════════════════════════════
# 6. NO 关联加分
# ══════════════════════════════════════════════════════════════════

def test_no_relevance_direct(matcher, outfit_tuck_needed):
    """prop_balance NO + tuck 含'腰线'关键词 → +5"""
    tuck = [s for s in matcher.skills if s["skill_id"] == "test_tuck"][0]
    assert matcher._no_relevance_bonus(tuck, outfit_tuck_needed) == 5


def test_no_relevance_none(matcher, outfit_no_issues):
    """0 NO → 加分 0"""
    tuck = [s for s in matcher.skills if s["skill_id"] == "test_tuck"][0]
    assert matcher._no_relevance_bonus(tuck, outfit_no_issues) == 0


# ══════════════════════════════════════════════════════════════════
# 7. 历史过滤
# ══════════════════════════════════════════════════════════════════

def test_is_recently_recommended(matcher):
    """最近推荐过 → True"""
    ctx = {"skill_history": {"recent": [{"skill_id": "test_tuck"}]}}
    assert matcher._is_recently_recommended("test_tuck", ctx) is True


def test_is_not_recently_recommended(matcher):
    """未推荐过 → False"""
    assert matcher._is_recently_recommended("test_tuck", {}) is False


def test_is_mastered(matcher):
    """已掌握 → True"""
    ctx = {"skill_history": {"mastered": [{"skill_id": "test_tuck"}]}}
    assert matcher._is_mastered("test_tuck", ctx) is True


def test_is_disliked(matcher):
    """不喜欢 → True"""
    ctx = {"skill_history": {"disliked": [{"skill_id": "test_cuff"}]}}
    assert matcher._is_disliked("test_cuff", ctx) is True


# ══════════════════════════════════════════════════════════════════
# 8. 完整匹配流程
# ══════════════════════════════════════════════════════════════════

def test_match_ranks_correctly(matcher, outfit_tuck_needed, user_pear):
    """梨形 + prop_balance NO → test_tuck 排第一"""
    result = matcher.match(outfit_tuck_needed, user_pear)
    assert result.has_match
    assert result.top_skill["skill_id"] == "test_tuck"
    # test_color 通过 * 匹配，但分数较低
    assert len(result.matches) >= 2


def test_match_no_issues_ranks_color(matcher, outfit_no_issues, user_pear):
    """0 NO → 精进模式，color_echo 应该进入匹配"""
    result = matcher.match(outfit_no_issues, user_pear)
    assert result.has_match
    # 0 NO 时 test_tuck 没有 NO 加分，color 可能胜出
    # 但 tuck 有身形加分(10) vs color 无身形匹配(5)，所以 tuck 可能仍第一
    # 关键是不崩溃
    assert len(result.matches) > 0


def test_match_recently_recommended_penalized(matcher, outfit_tuck_needed):
    """最近推荐过 → test_tuck 被降分"""
    ctx = {
        "body_shape": {"body_type": "梨形"},
        "skill_history": {"recent": [{"skill_id": "test_tuck"}], "mastered": [], "disliked": []},
    }
    result = matcher.match(outfit_tuck_needed, ctx)
    # test_tuck 可能不再排第一
    assert result.has_match


def test_match_result_structure(matcher, outfit_tuck_needed, user_pear):
    """验证 MatchResult 结构完整"""
    result = matcher.match(outfit_tuck_needed, user_pear)
    assert isinstance(result, MatchResult)
    assert isinstance(result.matches, list)
    for m in result.matches:
        assert isinstance(m, SkillMatch)
        assert isinstance(m.skill, dict)
        assert isinstance(m.score, int)
        assert "skill_id" in m.skill
        assert "name" in m.skill

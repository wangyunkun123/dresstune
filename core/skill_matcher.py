"""
技巧匹配引擎 — 基于穿搭数据和用户画像，从技巧库中匹配最合适的微调技巧。

Phase 3 升级：接入美学知识库 + 身体修饰符 + 风格方向 + 天气 + 美学协同。

用法：
    from core.skill_matcher import SkillMatcher
    matcher = SkillMatcher()
    result = matcher.match(outfit_data, user_context)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from core.aesthetics_loader import AestheticsKnowledge

logger = logging.getLogger("skill_matcher")


# ══════════════════════════════════════════════════════════════════
# 数据类
# ══════════════════════════════════════════════════════════════════

@dataclass
class SkillMatch:
    """单个技巧的匹配结果"""
    skill: dict
    score: int
    match_reasons: list[str] = field(default_factory=list)


@dataclass
class MatchResult:
    """技巧匹配的完整结果"""
    matches: list[SkillMatch] = field(default_factory=list)
    top_skill: Optional[dict] = None

    @property
    def has_match(self) -> bool:
        return self.top_skill is not None


# ══════════════════════════════════════════════════════════════════
# Checklist ID → 关键词（用于判断技巧是否解决某个 NO 项）
# ══════════════════════════════════════════════════════════════════

_CHECKLIST_KEYWORDS = {
    "fit_top": ["上装", "合身", "上衣"],
    "fit_bottom": ["下装", "裤长", "裤脚", "堆叠", "拖沓"],
    "fit_shoe": ["鞋", "比例", "裤脚", "遮盖"],
    "color_match": ["颜色", "配色", "色调", "花哨", "单调"],
    "style_match": ["风格", "调性", "不搭"],
    "prop_balance": ["比例", "腰线", "腿长", "上下身", "压"],
    "occasion": ["场合", "正式", "日常"],
}

# Checklist ID → 对应的美学维度（用于美学协同加分）
_CHECKLIST_TO_DIMENSION = {
    "fit_top": "silhouette",
    "fit_bottom": "proportion",
    "fit_shoe": "proportion",
    "color_match": "color",
    "style_match": "style",
    "prop_balance": "proportion",
    "occasion": "occasion",
}


# ══════════════════════════════════════════════════════════════════
# 匹配引擎
# ══════════════════════════════════════════════════════════════════

class SkillMatcher:
    """
    技巧匹配引擎。

    Phase 3 评分公式：
      score = body_type_score(0-10)
            + body_modifier_bonus(-5~+5)        [NEW]
            + NO_relevance(0~+5)
            + scenario_match(0~+3)
            + style_direction_bonus(0~+5)       [NEW]
            + aesthetics_synergy(0~+5)           [NEW]
            + weather_relevance(0~+3)            [NEW]
            + estimated_impact(0~+5)             [NEW]
            + difficulty_bonus(0~3)
            - recency_penalty(-15)
            - mastered_penalty(-8)
            - disliked_penalty(-20)
            - style_anti_synergy(-5)             [NEW]
    """

    def __init__(self, skills_dir: str = None, knowledge: AestheticsKnowledge = None):
        if skills_dir is None:
            skills_dir = Path(__file__).parent.parent / "knowledge" / "skills"
        self.skills_dir = Path(skills_dir)
        self._skills: Optional[list[dict]] = None

        if knowledge is None:
            knowledge = AestheticsKnowledge()
        self.knowledge = knowledge

    # ═══════════════════════════════════════════════════════════════
    # 加载
    # ═══════════════════════════════════════════════════════════════

    @property
    def skills(self) -> list[dict]:
        """懒加载所有技巧 JSON，加载后自动触发内容审查"""
        if self._skills is None:
            self._skills = []
            if self.skills_dir.exists():
                for f in sorted(self.skills_dir.glob("*.json")):
                    try:
                        skill = json.loads(f.read_text(encoding="utf-8"))
                        skill["_file"] = str(f.name)
                        self._skills.append(skill)
                    except Exception as e:
                        logger.warning(f"跳过损坏的技巧文件 {f.name}: {e}")
            logger.info(f"已加载 {len(self._skills)} 个技巧")

            # [Fix 3] 加载时自动审查技巧质量
            try:
                from core.content_reviewer import ContentReviewer
                reviewer = ContentReviewer()
                batch = reviewer.batch_review(self._skills)
                if batch.failed > 0:
                    logger.warning(f"⚠️ 技巧审查: {batch.failed} 个未通过")
                if batch.flagged > 0:
                    logger.info(f"📝 技巧审查: {batch.flagged} 个可改进")
            except Exception as e:
                logger.debug(f"技巧审查跳过: {e}")

        return self._skills

    def reload(self):
        """强制重新加载技巧库"""
        self._skills = None
        return self.skills

    # ═══════════════════════════════════════════════════════════════
    # 匹配
    # ═══════════════════════════════════════════════════════════════

    def match(
        self,
        outfit_data: dict,
        user_context: dict = None,
        top_n: int = 3,
    ) -> MatchResult:
        """
        匹配最佳技巧。

        Args:
            outfit_data: 段一穿搭解析 dict
            user_context: 用户上下文（body_shape, skill_history, weather, preferences）
            top_n: 返回前 N 个匹配

        Returns:
            MatchResult，含排名列表和 top_skill
        """
        if user_context is None:
            user_context = {}

        matched: list[SkillMatch] = []

        for skill in self.skills:
            # 第一关：品类筛选
            if not self._is_category_match(skill, outfit_data):
                continue

            # 第二关：不适用场景排除
            if self._is_inapplicable(skill, outfit_data):
                continue

            # ═══ 打分 ═══
            score = 0
            reasons = []

            # 1. 身形适配 (0-10)
            body_score = self._body_type_score(skill, user_context)
            score += body_score
            if body_score >= 8:
                reasons.append(f"身形匹配+{body_score}")

            # 2. 身体修饰符 (-5 ~ +5) [NEW]
            modifier_bonus = self._body_modifier_bonus(skill, user_context)
            score += modifier_bonus
            if modifier_bonus > 0:
                reasons.append(f"身体修饰符+{modifier_bonus}")
            elif modifier_bonus < 0:
                reasons.append(f"身体修饰符{modifier_bonus}")

            # 3. NO 项关联 (+5)
            no_bonus = self._no_relevance_bonus(skill, outfit_data)
            score += no_bonus
            if no_bonus > 0:
                reasons.append(f"直接解决NO项+{no_bonus}")

            # 4. 场景匹配 (+3)
            if self._is_scenario_match(skill, outfit_data):
                score += 3
                reasons.append("场景匹配+3")

            # 5. 风格方向匹配 (0 ~ +5) [NEW]
            style_bonus = self._style_direction_bonus(skill, user_context)
            score += style_bonus
            if style_bonus >= 4:
                reasons.append(f"风格契合+{style_bonus}")
            elif style_bonus > 0:
                reasons.append(f"风格适配+{style_bonus}")

            # 6. 美学协同 (0 ~ +5) [NEW]
            synergy = self._aesthetics_synergy_bonus(skill, outfit_data)
            score += synergy
            if synergy > 0:
                reasons.append(f"美学协同+{synergy}")

            # 7. 天气适配 (0 ~ +3) [NEW]
            weather_bonus = self._weather_relevance_bonus(skill, user_context)
            score += weather_bonus
            if weather_bonus > 0:
                reasons.append(f"天气适配+{weather_bonus}")

            # 8. 预估效果 (0 ~ +5) [NEW]
            impact_score = self._estimated_impact_score(skill)
            score += impact_score
            if impact_score >= 3:
                reasons.append(f"高效果+{impact_score}")

            # 9. 难度加分 (0 ~ 3)
            difficulty_bonus = max(0, 4 - skill.get("difficulty", 1))
            score += difficulty_bonus

            # 10. 风格反模式 (-5) [NEW]
            anti = self._style_anti_synergy(skill, user_context)
            score += anti
            if anti < 0:
                reasons.append(f"风格冲突{anti}")

            # 11. 推测数据降权 [NEW]
            if skill.get("techniques_inferred"):
                score -= 3
                reasons.append("推测技巧-3")

            # 12. 最近推荐过 (-15)
            if self._is_recently_recommended(skill["skill_id"], user_context):
                score -= 15
                reasons.append("最近推荐过-15")

            # 13. 已掌握 (-8)
            if self._is_mastered(skill["skill_id"], user_context):
                score -= 8
                reasons.append("已掌握-8")

            # 14. 用户不喜欢 (-20)
            if self._is_disliked(skill["skill_id"], user_context):
                score -= 20
                reasons.append("用户不喜欢-20")

            # 15. 反馈调整 (0 ~ -10) [Fix 6]
            feedback_adj = self._feedback_adjustment(skill["skill_id"], user_context)
            score += feedback_adj
            if feedback_adj < 0:
                reasons.append(f"反馈调整{feedback_adj}")

            matched.append(SkillMatch(skill=skill, score=score, match_reasons=reasons))

        # 按分数降序
        matched.sort(key=lambda m: m.score, reverse=True)
        top_matches = matched[:top_n]

        logger.info(
            f"匹配完成: {len(self.skills)} 个技巧 → {len(matched)} 个通过筛选 → "
            f"Top {len(top_matches)}: {[m.skill['name'] + f'({m.score})' for m in top_matches]}"
        )

        return MatchResult(
            matches=top_matches,
            top_skill=top_matches[0].skill if top_matches else None,
        )

    # ═══════════════════════════════════════════════════════════════
    # 筛选逻辑
    # ═══════════════════════════════════════════════════════════════

    def _is_category_match(self, skill: dict, outfit_data: dict) -> bool:
        """用户穿的单品中，至少有一件在技巧的适用品类里"""
        applicable = skill.get("applicable", {})
        cat_list = applicable.get("categories", [])
        if not cat_list:
            return True
        if "*" in cat_list:
            return True
        worn_cats = {item.get("category", "") for item in outfit_data.get("items", [])}
        return bool(worn_cats & set(cat_list))

    def _is_scenario_match(self, skill: dict, outfit_data: dict) -> bool:
        """穿搭场景是否匹配技巧适用场景"""
        scenarios = skill.get("applicable", {}).get("scenarios", [])
        if not scenarios:
            return False
        no_texts = []
        for c in outfit_data.get("checklist", []):
            if c.get("result") == "NO":
                no_texts.append(c.get("question", ""))
                no_texts.append(c.get("reason", ""))
        no_texts.append(outfit_data.get("outfit_description", ""))
        combined = " ".join(no_texts)
        return any(kw in combined for kw in scenarios)

    def _is_inapplicable(self, skill: dict, outfit_data: dict) -> bool:
        """检查品类黑名单。文本场景判断交给 LLM。"""
        inapplicable = skill.get("inapplicable", {})
        bad_cats = set(inapplicable.get("categories", []))
        worn_cats = {item.get("category", "") for item in outfit_data.get("items", [])}
        if bad_cats and (worn_cats & bad_cats):
            logger.debug(f"  {skill['skill_id']}: 品类不适用 ({worn_cats & bad_cats})")
            return True
        return False

    # ═══════════════════════════════════════════════════════════════
    # 打分逻辑
    # ═══════════════════════════════════════════════════════════════

    def _body_type_score(self, skill: dict, user_context: dict) -> int:
        """根据用户体型返回适配分数 (0-10)"""
        body = user_context.get("body_shape") or user_context.get("body", {})
        body_type = body.get("body_type", "")
        if not body_type:
            return 5
        body_scores = skill.get("applicable", {}).get("body_types", {})
        match = body_scores.get(body_type)
        if match:
            return match.get("score", 5)
        return 5

    def _body_modifier_bonus(self, skill: dict, user_context: dict) -> int:
        """
        [Phase 3 NEW] 身体修饰符加分。
        读取 skill.body_modifiers，与用户的肩胯比/腿身比/身高等特征匹配。
        Returns -5 ~ +5。
        """
        body = user_context.get("body_shape") or user_context.get("body", {})
        modifiers = skill.get("body_modifiers", {})
        if not modifiers:
            return 0

        bonus = 0
        # 肩胯比
        sh_ratio = body.get("shoulder_hip_ratio", "")
        if "肩窄胯宽" in sh_ratio:
            # 梨形 → 窄肩体征
            if "narrow_shoulders" in modifiers:
                bonus += modifiers["narrow_shoulders"].get("bonus", 0)
        elif "肩宽胯窄" in sh_ratio:
            # 倒三角 → 宽肩体征
            if "broad_shoulders" in modifiers:
                bonus += modifiers["broad_shoulders"].get("bonus", 0)

        # 腿身比
        leg_ratio = body.get("leg_body_ratio") or body.get("leg_torso_ratio", "")
        if "短" in leg_ratio or "偏短" in leg_ratio:
            if "short_legs" in modifiers:
                bonus += modifiers["short_legs"].get("bonus", 0)

        # 躯干
        torso = body.get("torso_length", "")
        if "长" in torso:
            if "long_torso" in modifiers:
                bonus += modifiers["long_torso"].get("bonus", 0)

        # 腰腹
        if "thick_waist" in modifiers and body.get("body_type") == "苹果":
            bonus += modifiers["thick_waist"].get("bonus", 0)

        return max(-5, min(5, bonus))

    def _style_direction_bonus(self, skill: dict, user_context: dict) -> int:
        """
        [Phase 3 NEW] 风格方向匹配加分。
        用户 preferred_style 在 skill 的 style_variants 中= +5，
        在 related_styles 中= +2，
        techniques_inferred= +3 而非 +5。
        """
        prefs = user_context.get("preferences", {})
        preferred = prefs.get("preferred_style", "")
        if not preferred:
            return 0

        variants = skill.get("style_variants", {})
        if preferred in variants:
            # 有专属执行方式 = 完美匹配
            if skill.get("techniques_inferred"):
                return 3  # 推测数据降权
            return 5

        # 检查是否在 related_styles 中（需访问知识库）
        style_data = self.knowledge.get_style_direction(preferred)
        if style_data:
            related = set(style_data.get("related_styles", []))
            if skill.get("series") == "tuck_methods" and any(
                s in related for s in ["clean_fit", "city_boy", "smart_casual"]
            ):
                return 2

        return 0

    def _style_anti_synergy(self, skill: dict, user_context: dict) -> int:
        """
        [Phase 3 NEW] 风格反模式罚分。
        用户 preferred_style 在 skill 的 style_anti_patterns 中 = -5。
        """
        prefs = user_context.get("preferences", {})
        preferred = prefs.get("preferred_style", "")
        if not preferred:
            return 0

        anti = set(skill.get("style_anti_patterns", []))
        if preferred in anti:
            return -5
        return 0

    def _aesthetics_synergy_bonus(self, skill: dict, outfit_data: dict) -> int:
        """
        [Phase 3 NEW] 美学协同加分。
        如果技巧的 aesthetics_dimensions 正好覆盖了 checklist 的弱点维度，+5。
        如果覆盖了 checklist 已有优势的维度，+2（锦上添花）。
        """
        dims = skill.get("aesthetics_dimensions", [])
        if not dims:
            return 0

        # 找出 NO 项对应的美学维度
        weak_dims = set()
        for c in outfit_data.get("checklist", []):
            if c.get("result") == "NO":
                dim = _CHECKLIST_TO_DIMENSION.get(c.get("id", ""))
                if dim:
                    weak_dims.add(dim)

        # 找出 YES 项对应的美学维度
        strong_dims = set()
        for c in outfit_data.get("checklist", []):
            if c.get("result") == "YES":
                dim = _CHECKLIST_TO_DIMENSION.get(c.get("id", ""))
                if dim:
                    strong_dims.add(dim)

        skill_dims = {d.get("dimension", "") for d in dims}

        # 直接解决弱点 → 高分
        if skill_dims & weak_dims:
            return 5
        # 锦上添花 → 低分
        if skill_dims & strong_dims:
            return 2
        return 0

    def _weather_relevance_bonus(self, skill: dict, user_context: dict) -> int:
        """
        [Phase 3 NEW] 天气适配加分。
        skill.seasons 包含当前季节 = +2。
        温度敏感技巧：temp 低于 weather_min_temp = -3。
        """
        weather = user_context.get("weather", {})
        if not weather:
            return 0

        season = weather.get("season", "")
        skill_seasons = skill.get("seasons", [])
        bonus = 0

        # 季节匹配
        season_map = {"冬季": "winter", "春季": "spring", "夏季": "summer", "秋季": "autumn"}
        season_en = season_map.get(season, season.lower() if season else "")
        if season_en and season_en in skill_seasons:
            bonus += 2
        elif "*" in skill_seasons or len(skill_seasons) == 4:
            bonus += 2

        # 温度敏感
        if skill.get("weather_sensitive"):
            temp = weather.get("temperature")
            min_temp = skill.get("weather_min_temp")
            if temp is not None and min_temp is not None:
                if temp < min_temp:
                    bonus -= 3
                    logger.debug(f"  {skill['skill_id']}: 温度{temp}°C < 最低{min_temp}°C → -3")

        return max(-3, min(3, bonus))

    def _estimated_impact_score(self, skill: dict) -> int:
        """
        [Phase 3 NEW] 预估效果分。
        从 estimated_impact 中各维度取最大值，映射到 0-5。
        """
        impact = skill.get("estimated_impact", {})
        if not impact:
            return 2  # 默认中等
        max_val = max(impact.values())
        if max_val >= 15:
            return 5
        elif max_val >= 10:
            return 3
        elif max_val >= 5:
            return 2
        return 1

    def _no_relevance_bonus(self, skill: dict, outfit_data: dict) -> int:
        """如果技巧能直接解决某个 NO 项，给加分"""
        no_items = [
            c for c in outfit_data.get("checklist", [])
            if c.get("result") == "NO"
        ]
        if not no_items:
            return 0

        skill_scenarios = " ".join(skill.get("applicable", {}).get("scenarios", []))
        skill_name = skill.get("name", "")
        skill_desc = skill.get("description", "")

        for no_item in no_items:
            no_id = no_item.get("id", "")
            keywords = _CHECKLIST_KEYWORDS.get(no_id, [])
            search_text = skill_scenarios + skill_name + skill_desc

            if any(kw in search_text for kw in keywords):
                return 5
            question = no_item.get("question", "")
            if any(kw in search_text for kw in question.split("？")[0].split()):
                return 3

        return 0

    # ═══════════════════════════════════════════════════════════════
    # 历史检查
    # ═══════════════════════════════════════════════════════════════

    def _is_recently_recommended(self, skill_id: str, user_context: dict) -> bool:
        skill_history = user_context.get("skill_history", {})
        recent = skill_history.get("recent") or skill_history.get("recently_recommended", [])
        for r in recent:
            rid = r.get("skill_id", "") if isinstance(r, dict) else r
            if rid == skill_id:
                return True
        return False

    def _is_mastered(self, skill_id: str, user_context: dict) -> bool:
        skill_history = user_context.get("skill_history", {})
        mastered = skill_history.get("mastered") or skill_history.get("mastered_skills", [])
        for m in mastered:
            mid = m.get("skill_id", "") if isinstance(m, dict) else m
            if mid == skill_id:
                return True
        for m in mastered:
            mname = m.get("skill_name", m.get("name", "")) if isinstance(m, dict) else m
            if mname and mname in self._get_skill_name(skill_id):
                return True
        return False

    def _is_disliked(self, skill_id: str, user_context: dict) -> bool:
        skill_history = user_context.get("skill_history", {})
        disliked = skill_history.get("disliked") or skill_history.get("disliked_skills", [])
        for d in disliked:
            did = d.get("skill_id", "") if isinstance(d, dict) else d
            if did == skill_id:
                return True
        return False

    def _get_skill_name(self, skill_id: str) -> str:
        for s in self.skills:
            if s["skill_id"] == skill_id:
                return s.get("name", "")
        return ""

    def _feedback_adjustment(self, skill_id: str, user_context: dict) -> int:
        """
        [Fix 6] 反馈驱动的评分调整。
        用户级：该用户给此技巧反馈 'worse' → -5
        系列级：该用户对此系列 'worse' 率 >30% → -3
        全局级：此技巧全局 'worse' 率 >30% → -8
        """
        user_id = user_context.get("user_id", "")
        if not user_id:
            return 0

        try:
            from core.feedback_store import FeedbackStore
            store = FeedbackStore()
            adjustment = 0

            # 用户级
            last = store.get_user_skill_feedback(user_id, skill_id)
            if last and last.get("feedback") == "worse":
                adjustment -= 5

            # 系列级
            skill = self._find_skill(skill_id)
            if skill:
                series = skill.get("series", "")
                if series:
                    series_stats = store.get_user_series_stats(user_id, series, self.skills)
                    if series_stats.get("worse_rate", 0) > 0.30 and series_stats.get("total", 0) >= 3:
                        adjustment -= 3

            # 全局级
            global_stats = store.get_skill_stats(skill_id)
            if global_stats.get("flagged"):
                adjustment -= 8

            return max(-10, adjustment)
        except Exception:
            return 0

    def _find_skill(self, skill_id: str) -> dict | None:
        for s in self.skills:
            if s["skill_id"] == skill_id:
                return s
        return None

    # ═══════════════════════════════════════════════════════════════
    # 原理查询（供 suggestion.py 使用）
    # ═══════════════════════════════════════════════════════════════

    def get_principles_for_skill(self, skill_id: str) -> list[dict]:
        """获取某技巧涉及的所有美学原则（从 skills 反向索引）"""
        return self.knowledge.get_principles_for_skill(skill_id, self.skills)


# ══════════════════════════════════════════════════════════════════
# 快速测试
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    print("=" * 60)
    print("SkillMatcher Phase 3 — 自检")
    print("=" * 60)

    matcher = SkillMatcher()
    print(f"\n已加载 {len(matcher.skills)} 个技巧:")
    for s in matcher.skills:
        has_mod = bool(s.get("body_modifiers"))
        has_style = bool(s.get("style_variants"))
        has_impact = bool(s.get("estimated_impact"))
        inferred = s.get("techniques_inferred", False)
        tags = []
        if has_mod:
            tags.append("modifiers")
        if has_style:
            tags.append("style")
        if has_impact:
            tags.append("impact")
        if inferred:
            tags.append("inferred")
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        print(f"  - {s['skill_id']}: {s['name']} (难度{s['difficulty']}){tag_str}")

    # 模拟测试 — 精进模式 + Clean Fit 风格
    mock_outfit = {
        "outfit_description": "白色宽松短袖T恤搭配深蓝色直筒牛仔裤",
        "items": [
            {"category": "TS", "category_cn": "短袖T恤", "color": "白色", "fit": "宽松", "wearing_style": "常规（下摆未塞）"},
            {"category": "JEANS", "category_cn": "牛仔裤", "color": "深蓝色", "fit": "直筒", "wearing_style": "常规穿着"},
        ],
        "checklist": [
            {"id": "fit_top", "question": "上装合身吗？", "result": "YES", "reason": ""},
            {"id": "prop_balance", "question": "上下身比例舒服吗？", "result": "NO", "reason": "T恤太长压腿长"},
        ],
    }

    # 梨形 + Clean Fit 用户
    context_pear_cf = {
        "body_shape": {"body_type": "梨形", "shoulder_hip_ratio": "肩窄胯宽", "leg_body_ratio": "腿偏短", "height": 170},
        "skill_history": {"mastered": [], "recent": [], "disliked": []},
        "preferences": {"preferred_style": "clean_fit"},
        "weather": {"condition": "晴天", "temperature": 28, "season": "夏季"},
    }

    result = matcher.match(mock_outfit, context_pear_cf)
    print(f"\n🍐 梨形 + Clean Fit + T恤牛仔裤 + prop_balance NO:")
    for i, m in enumerate(result.matches):
        print(f"  {i+1}. {m.skill['name']} ({m.skill['skill_id']}) — {m.score}分 — {m.match_reasons}")

    # 矩形 + City Boy 用户
    context_rect_cb = {
        "body_shape": {"body_type": "矩形", "shoulder_hip_ratio": "肩胯同宽", "leg_body_ratio": "均衡", "height": 175},
        "skill_history": {"mastered": [], "recent": [], "disliked": []},
        "preferences": {"preferred_style": "city_boy"},
        "weather": {"condition": "晴天", "temperature": 28, "season": "夏季"},
    }

    result2 = matcher.match(mock_outfit, context_rect_cb)
    print(f"\n📐 矩形 + City Boy + T恤牛仔裤 + prop_balance NO:")
    for i, m in enumerate(result2.matches):
        print(f"  {i+1}. {m.skill['name']} ({m.skill['skill_id']}) — {m.score}分 — {m.match_reasons}")

    # 对比：同样的穿搭，不同风格方向的推荐是否不同
    top1_cf = result.matches[0].skill["name"] if result.matches else "N/A"
    top1_cb = result2.matches[0].skill["name"] if result2.matches else "N/A"
    print(f"\n🔀 同衣不同建议:")
    print(f"  梨形+Clean Fit → {top1_cf}")
    print(f"  矩形+City Boy → {top1_cb}")
    print(f"  差异化: {'✅' if top1_cf != top1_cb else '❌ 相同'}")

    # 原理测试
    if result.top_skill:
        principles = matcher.get_principles_for_skill(result.top_skill["skill_id"])
        print(f"\n📖 {result.top_skill['name']} 的美学原理 ({len(principles)} 条):")
        for p in principles[:3]:
            print(f"  [{p['dimension_name']}] {p.get('name_cn', '')}: {p.get('statement', '')[:50]}...")

    print("\n✅ SkillMatcher Phase 3 自检完成。")

"""
穿搭微调建议引擎。

基于 AI 穿搭分析结果，生成具体、可操作的微调建议。
三段流程：
  1. SkillMatcher 从技巧库匹配最佳技巧
  2. LLM 基于匹配结果定制文案（身形适配、场景个性化）
  3. Hard Filters 硬过滤兜底

用法：
    from core.suggestion import SuggestionEngine
    engine = SuggestionEngine()
    result = engine.generate(outfit_data, user_context)
"""

from __future__ import annotations

import json
import time
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from core.ai_router import AIRouter, extract_json
from core.skill_matcher import SkillMatcher

logger = logging.getLogger("suggestion")


# ══════════════════════════════════════════════════════════════════
# 数据类
# ══════════════════════════════════════════════════════════════════

@dataclass
class SuggestionDetail:
    """单条微调建议的完整信息"""
    skill_id: str = ""
    skill_name: str = ""
    headline: str = ""
    why: str = ""
    how_to: str = ""
    expected_effect: str = ""
    difficulty: int = 1
    estimated_time_seconds: int = 10


@dataclass
class SuggestionResult:
    """微调建议生成的完整返回"""
    success: bool = False
    scene: str = ""                        # 精进/微调/纠正
    checklist_summary: dict = field(default_factory=dict)
    suggestion: Optional[SuggestionDetail] = None
    tone: str = "friendly"
    encouragement: str = ""
    model_used: str = ""
    latency_ms: float = 0.0
    error: Optional[str] = None


# ══════════════════════════════════════════════════════════════════
# 建议引擎
# ══════════════════════════════════════════════════════════════════

class SuggestionEngine:
    """
    穿搭微调建议生成引擎。

    封装 LLM 调用，将穿搭分析数据转化为用户可操作的微调建议。
    """

    def __init__(self, router: AIRouter = None, prompt_dir: str = None, matcher: SkillMatcher = None):
        """
        Args:
            router: AIRouter 实例，默认自动创建
            prompt_dir: prompt 模板目录，默认 ../prompts（相对于本文件）
            matcher: SkillMatcher 实例，默认自动创建
        """
        if router is None:
            router = AIRouter()
        self.router = router

        if prompt_dir is None:
            prompt_dir = Path(__file__).parent.parent / "prompts"
        self.prompt_dir = Path(prompt_dir)

        if matcher is None:
            matcher = SkillMatcher()
        self.matcher = matcher

        self._system_prompt: Optional[str] = None

    # ═══════════════════════════════════════════════════════════════
    # Prompt
    # ═══════════════════════════════════════════════════════════════

    @property
    def system_prompt(self) -> str:
        """懒加载 prompts/suggestion.md"""
        if self._system_prompt is None:
            prompt_path = self.prompt_dir / "suggestion.md"
            with open(prompt_path, "r", encoding="utf-8") as f:
                self._system_prompt = f.read()
            logger.info(f"已加载 system prompt: {prompt_path} ({len(self._system_prompt)} 字符)")
        return self._system_prompt

    # ═══════════════════════════════════════════════════════════════
    # 核心方法
    # ═══════════════════════════════════════════════════════════════

    def generate(
        self,
        outfit_data: dict,
        user_context: dict = None,
    ) -> SuggestionResult:
        """
        生成穿搭微调建议。

        流程：
        1. 用 _build_user_message() 构建用户消息
        2. 调用 router.chat(task="suggestion", ..., response_format={"type": "json_object"})
        3. extract_json() 提取 JSON
        4. 构造 SuggestionResult
        5. 自动执行 apply_hard_filters() 硬过滤兜底

        Args:
            outfit_data: 穿搭分析数据，包含描述、风格、单品列表、checklist 等
            user_context: 用户上下文，可包含身形、技巧历史、天气等

        Returns:
            SuggestionResult
        """
        if user_context is None:
            user_context = {}

        try:
            # 步骤 0：技巧库匹配
            match_result = self.matcher.match(outfit_data, user_context)
            matched_skill = match_result.top_skill  # dict or None

            user_message = self._build_user_message(outfit_data, user_context, matched_skill)

            t_start = time.time()
            result = self.router.chat(
                task="suggestion",
                system_prompt=self.system_prompt,
                user_message=user_message,
                response_format={"type": "json_object"},
            )

            latency_ms = (time.time() - t_start) * 1000

            if not result.success:
                return SuggestionResult(
                    success=False,
                    error=result.error or "LLM 调用失败",
                    model_used=result.model_used,
                    latency_ms=result.latency_ms,
                )

            # 用 router 实际耗时（含重试）替代本地计时
            if result.latency_ms > 0:
                latency_ms = result.latency_ms

            data = extract_json(result.data)
            if data is None:
                logger.warning(f"无法从 LLM 输出中提取 JSON: {result.data[:300]}...")
                return SuggestionResult(
                    success=False,
                    error="JSON 解析失败",
                    model_used=result.model_used,
                    latency_ms=latency_ms,
                )

            # 构造 SuggestionDetail
            sug_data = data.get("suggestion", {})
            suggestion = SuggestionDetail(
                skill_id=sug_data.get("skill_id", ""),
                skill_name=sug_data.get("skill_name", ""),
                headline=sug_data.get("headline", ""),
                why=sug_data.get("why", ""),
                how_to=sug_data.get("how_to", ""),
                expected_effect=sug_data.get("expected_effect", ""),
                difficulty=sug_data.get("difficulty", 1),
                estimated_time_seconds=sug_data.get("estimated_time_seconds", 10),
            )

            raw_result = SuggestionResult(
                success=True,
                scene=data.get("scene", ""),
                checklist_summary=data.get("checklist_summary", {}),
                suggestion=suggestion,
                tone=data.get("tone", "friendly"),
                encouragement=data.get("encouragement", ""),
                model_used=result.model_used,
                latency_ms=latency_ms,
            )

            # 硬过滤兜底：自动检查并拦截违反规则的推荐
            return apply_hard_filters(raw_result, outfit_data)

        except Exception as e:
            logger.error(f"生成建议异常: {e}", exc_info=True)
            return SuggestionResult(
                success=False,
                error=str(e),
            )

    # ═══════════════════════════════════════════════════════════════
    # 用户消息构建
    # ═══════════════════════════════════════════════════════════════

    def _build_user_message(
        self,
        outfit_data: dict,
        user_context: dict,
        matched_skill: dict = None,
    ) -> str:
        """
        构建发给 LLM 的用户消息。

        数据契约与 outfit_parser.to_dict() 输出对齐。
        如果 matched_skill 不为空，LLM 将基于该技巧定制文案而非自由创作。
        """
        parts = []

        # ── 1. 穿搭数据 ──
        parts.append("## 当前穿搭数据")
        parts.append("")

        outfit_desc = outfit_data.get("outfit_description", "")
        if outfit_desc:
            parts.append(f"整体描述：{outfit_desc}")
            parts.append("")

        overall_style = outfit_data.get("overall_style", "")
        if overall_style:
            parts.append(f"整体风格：{overall_style}")
            parts.append("")

        # ❌ 数量 + ❌ 项（来自计算属性）
        no_count = outfit_data.get("no_count", 0)
        no_items = outfit_data.get("no_items", [])
        parts.append(f"Checklist ❌ 数量：{no_count}")
        if no_items:
            parts.append(f"❌ 项：{', '.join(no_items)}")
        parts.append("")

        # 单品列表
        items = outfit_data.get("items", [])
        if items:
            parts.append("### 穿着单品")
            parts.append("")
            for i, item in enumerate(items, 1):
                cat = item.get("category", "?")
                cat_cn = item.get("category_cn", "")
                label = f"{cat_cn}（{cat}）" if cat_cn else cat
                color = item.get("color", "")
                sec_color = item.get("secondary_color", "")
                color_str = f"{color}/{sec_color}" if sec_color else color
                fit = item.get("fit", "")
                wearing_style = item.get("wearing_style", "")
                notes = item.get("notes", "")

                lines = [f"{i}. {label} | {color_str} | {fit} | 穿法：{wearing_style}"]
                if notes:
                    lines.append(f"   备注：{notes}")
                parts.append("\n".join(lines))
            parts.append("")

        # Checklist 明细
        checklist = outfit_data.get("checklist", [])
        if checklist:
            parts.append("### Checklist 明细")
            parts.append("")
            for c in checklist:
                icon = "✅" if c.get("result") == "YES" else "❌"
                q = c.get("question", "")
                reason = c.get("reason", "")
                line = f"- {icon} {q}"
                if reason:
                    line += f" — {reason}"
                parts.append(line)
            parts.append("")

        # ── 2. 用户身形 ──
        # 兼容 body_shape 和 body 两种 key
        body = user_context.get("body_shape") or user_context.get("body", {})
        if body:
            parts.append("## 用户身形")
            parts.append("")
            for key, label in [
                ("body_type", "体型"),
                ("shoulder_hip_ratio", "肩胯比"),
                ("leg_body_ratio", "腿身比"),
                ("skin_tone", "肤色"),
            ]:
                val = body.get(key, "")
                if val:
                    parts.append(f"- {label}：{val}")
            if body.get("height"):
                parts.append(f"- 身高：{body['height']}cm")
            parts.append("")

        # ── 3. 技巧历史 ──
        skill_history = user_context.get("skill_history", {})
        if skill_history:
            parts.append("## 技巧历史")
            parts.append("")

            mastered = skill_history.get("mastered") or skill_history.get("mastered_skills", [])
            if mastered:
                parts.append(f"已掌握技巧：{', '.join(mastered)}")
                parts.append("")

            recent = skill_history.get("recent") or skill_history.get("recently_recommended", [])
            if recent:
                parts.append("最近 7 天内推荐过（避免重复）：")
                for r in recent:
                    if isinstance(r, str):
                        parts.append(f"  - {r}")
                    else:
                        parts.append(f"  - {r.get('skill_name', r.get('name', ''))}")
                parts.append("")

            disliked = skill_history.get("disliked") or skill_history.get("disliked_skills", [])
            if disliked:
                parts.append("用户反馈较差的技巧（避免推荐）：")
                for d in disliked:
                    if isinstance(d, str):
                        parts.append(f"  - {d}")
                    else:
                        parts.append(f"  - {d.get('skill_name', d.get('name', ''))}")
                parts.append("")

        # ── 4. 天气 ──
        weather = user_context.get("weather", {})
        if weather:
            parts.append("## 天气")
            parts.append("")
            condition = weather.get("condition", "")
            temp = weather.get("temperature", "")
            if condition and temp:
                parts.append(f"{condition} | {temp}°C")
            elif condition:
                parts.append(f"{condition}")
            season = weather.get("season", "")
            if season:
                parts.append(f"季节：{season}")
            parts.append("")

        # ── 5. 技巧库匹配结果（LLM 须基于此定制，而非自由创作）──
        if matched_skill:
            parts.append("## 系统匹配的技巧（你必须推荐这个技巧）")
            parts.append("")
            parts.append(f"你的任务不是决定推荐什么技巧——系统已经匹配好了。")
            parts.append(f"你的任务是把以下技巧内容，针对这个用户的身形、今天的穿搭、天气，")
            parts.append(f"改写成自然的朋友聊天口吻。可以调整措辞但不能改变技巧本身。")
            parts.append("")
            parts.append(f"### 匹配技巧：{matched_skill.get('name', '')}")
            parts.append(f"- skill_id: {matched_skill.get('skill_id', '')}")
            parts.append(f"- 难度: {matched_skill.get('difficulty', 1)} 星")
            parts.append(f"- headline: {matched_skill.get('headline', '')}")
            parts.append(f"- 为什么有效: {matched_skill.get('why_it_works', '')}")
            parts.append(f"- 预期效果: {matched_skill.get('expected_effect', '')}")
            parts.append("")
            parts.append("### 操作步骤")
            for i, step in enumerate(matched_skill.get("steps", []), 1):
                parts.append(f"{i}. {step}")
            parts.append("")

            # 身形适配
            body = user_context.get("body_shape") or user_context.get("body", {})
            body_type = body.get("body_type", "")
            if body_type:
                body_scores = matched_skill.get("applicable", {}).get("body_types", {})
                bt = body_scores.get(body_type, {})
                if bt:
                    parts.append(f"### 针对 {body_type} 体型的特别说明")
                    parts.append(f"{bt.get('note', '')}")
                    parts.append("")

            # 常见错误
            mistakes = matched_skill.get("common_mistakes", [])
            if mistakes:
                parts.append("### 常见错误（提醒用户避免）")
                for m in mistakes:
                    parts.append(f"- {m}")
                parts.append("")

            # [Phase 3 NEW] 美学原理（让 LLM 引用原理增强说服力）
            principles = self.matcher.get_principles_for_skill(matched_skill.get("skill_id", ""))
            if principles:
                parts.append("### 这个技巧背后的美学原理（你可以在 why 中引用）")
                for p in principles[:3]:  # 最多3条，避免信息过载
                    parts.append(f"- [{p.get('dimension_name', '')}] {p.get('statement', '')}")
                parts.append("")

        return "\n".join(parts)


# ══════════════════════════════════════════════════════════════════
# 硬过滤规则（代码层兜底，防止 LLM 不遵守 Prompt 中的禁用规则）
# ══════════════════════════════════════════════════════════════════

# 已知问题：Prompt 中"短袖不推荐袖口翻折"等规则有时不被遵守，代码层兜底。
# 用品类代码做精确匹配，不用字符串搜。

_SHORT_SLEEVE_CODES = {"TS", "POLO", "LS"}   # LS=长袖但也可卷，这里保守排除所有T恤类
_SHORTS_CODES = {"SHORTS"}
_NO_BUTTON_CODES = {"TS", "LS", "KNIT", "HOODIE", "SWEAT"}  # 无扣上衣

_FORBIDDEN_SKILL_RULES: list[dict] = [
    {
        "skill_ids": {"sleeve_roll", "sleeve_fold", "cuff_roll_sleeve"},
        "description": "短袖上衣不要推荐袖口翻折",
        "check": lambda outfit_data: any(
            item.get("category", "") in _SHORT_SLEEVE_CODES
            for item in outfit_data.get("items", [])
        ),
    },
    {
        "skill_ids": {"cuff_roll", "pant_cuff"},
        "description": "短裤不要推荐裤脚卷边",
        "check": lambda outfit_data: any(
            item.get("category", "") in _SHORTS_CODES
            for item in outfit_data.get("items", [])
        ),
    },
    {
        "skill_ids": {"button_rules", "button_rule"},
        "description": "无扣上衣不要推荐扣子法则",
        "check": lambda outfit_data: all(
            item.get("category", "") in _NO_BUTTON_CODES
            for item in outfit_data.get("items", [])
            if item.get("category", "") in {"TS", "LS", "SHIRT", "POLO", "KNIT", "HOODIE", "SWEAT", "JK", "COAT", "BLAZER"}
        ),
    },
]


def apply_hard_filters(
    result: SuggestionResult,
    outfit_data: dict,
) -> SuggestionResult:
    """
    对 LLM 返回的建议执行硬过滤。纯函数，不修改入参。

    如果建议的 skill_id 命中禁用规则，返回 success=False + error。
    """
    if not result.success or result.suggestion is None:
        return result

    for rule in _FORBIDDEN_SKILL_RULES:
        if result.suggestion.skill_id in rule["skill_ids"]:
            if rule["check"](outfit_data):
                logger.warning(
                    f"硬过滤触发 — skill={result.suggestion.skill_id} "
                    f"reason={rule['description']}"
                )
                return SuggestionResult(
                    success=False,
                    scene=result.scene,
                    error=f"[硬过滤] {rule['description']}",
                    model_used=result.model_used,
                    latency_ms=result.latency_ms,
                )

    return result


# ══════════════════════════════════════════════════════════════════
# 快速测试
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("SuggestionEngine 模块加载成功")
    print("=" * 60)

    engine = SuggestionEngine()
    print(f"\nSystem Prompt 长度: {len(engine.system_prompt)} 字符")
    print(f"Prompt 文件: {engine.prompt_dir / 'suggestion.md'}")

    # ── 模拟穿搭数据（与 outfit_parser.to_dict() 格式对齐）──
    mock_outfit = {
        "outfit_description": "白色宽松短袖T恤搭配深蓝色直筒牛仔裤，脚穿白色帆布鞋",
        "overall_style": "休闲简约",
        "no_count": 1,
        "no_items": ["下装合身吗？"],
        "items": [
            {
                "category": "TS",
                "category_cn": "短袖T恤",
                "color": "白色",
                "secondary_color": "",
                "fit": "宽松",
                "wearing_style": "常规",
                "notes": "纯棉面料",
            },
            {
                "category": "JEANS",
                "category_cn": "牛仔裤",
                "color": "深蓝色",
                "secondary_color": "",
                "fit": "直筒",
                "wearing_style": "常规穿着",
                "notes": "",
            },
            {
                "category": "SHOES_SNKR",
                "category_cn": "运动鞋",
                "color": "白色",
                "secondary_color": "",
                "fit": "标准",
                "wearing_style": "常规",
                "notes": "帆布鞋",
            },
        ],
        "checklist": [
            {"id": "color_match", "question": "颜色搭配协调吗？", "result": "YES", "reason": "白+蓝经典搭配"},
            {"id": "prop_balance", "question": "上下身比例舒服吗？", "result": "NO", "reason": "裤长稍长堆在鞋面上"},
            {"id": "occasion", "question": "适合日常出门吗？", "result": "YES", "reason": ""},
            {"id": "style_match", "question": "上下装风格一致吗？", "result": "YES", "reason": "休闲统一"},
            {"id": "fit_top", "question": "上装合身吗？", "result": "YES", "reason": ""},
            {"id": "fit_bottom", "question": "下装合身吗？", "result": "YES", "reason": ""},
            {"id": "fit_shoe", "question": "鞋与整体比例协调吗？", "result": "YES", "reason": ""},
        ],
    }

    # ── 模拟用户上下文 ──
    mock_context = {
        "body": {
            "body_type": "梨形",
            "shoulder_hip_ratio": "肩窄胯宽",
            "leg_torso_ratio": "腿偏短",
            "skin_tone": "暖白皮",
            "height": 170,
        },
        "skill_history": {
            "mastered_skills": ["法式半塞", "颜色呼应"],
            "recently_recommended": [
                {"skill_name": "袖口翻折", "date": "2026-06-25"},
            ],
            "disliked_skills": [],
        },
        "weather": {
            "condition": "晴天",
            "temperature": 28,
            "season": "夏季",
        },
        "preferences": {
            "preferred_style": "韩系简约",
            "goal": "显高显瘦",
        },
    }

    print("\n" + "-" * 40)
    print("模拟用户消息预览（前 800 字符）：")
    print("-" * 40)
    user_msg = engine._build_user_message(mock_outfit, mock_context)
    print(user_msg[:800])
    print(f"\n...（总长 {len(user_msg)} 字符）")

    # ── 测试硬过滤 ──
    print("\n" + "-" * 40)
    print("硬过滤规则测试：")
    print("-" * 40)

    # 测试 1：穿短袖 + 袖口翻折建议 → 应被过滤
    test_result = SuggestionResult(
        success=True,
        scene="微调",
        suggestion=SuggestionDetail(
            skill_id="sleeve_roll",
            skill_name="袖口翻折",
        ),
    )
    filtered = apply_hard_filters(test_result, mock_outfit)
    print(f"  场景：短袖 + 袖口翻折建议 → success={filtered.success}, error={filtered.error}")

    # 测试 2：穿短袖 + 裤脚卷边建议 → 不应被过滤（因为穿了长裤）
    test_result2 = SuggestionResult(
        success=True,
        scene="微调",
        suggestion=SuggestionDetail(
            skill_id="cuff_roll",
            skill_name="裤脚卷边",
        ),
    )
    filtered2 = apply_hard_filters(test_result2, mock_outfit)
    print(f"  场景：长裤 + 裤脚卷边建议 → success={filtered2.success} (应保留)")

    print("\n✅ SuggestionEngine 自检完成。调用 engine.generate() 生成真实建议。")

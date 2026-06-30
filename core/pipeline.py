from __future__ import annotations

"""
端到端穿搭分析管线。
串联 段一（穿搭解析）+ 段二（建议生成）+ 硬过滤，一键从照片到建议。

用法：
    from core.pipeline import run_pipeline
    result = run_pipeline("photo.jpg", user_context={...})
"""

import logging
import time
from pathlib import Path
from typing import Optional

from core.outfit_parser import OutfitParser
from core.suggestion import SuggestionEngine, apply_hard_filters
from core.effect_renderer import EffectRenderer

logger = logging.getLogger("pipeline")


def run_pipeline(
    photo_path: str,
    user_context: Optional[dict] = None,
    skip_suggestion: bool = False,
    skip_rendering: bool = False,
    timeout: float = 30.0,
) -> dict:
    """
    从照片到效果图的完整三段管线。

    Args:
        photo_path: 穿搭照片路径
        user_context: 用户上下文（body_shape, skill_history, weather 等）
        skip_suggestion: 跳过段二，仅返回穿搭解析结果
        skip_rendering: 跳过段三效果图生成（默认 False）
        timeout: 每段超时秒数（默认 30s），0 表示不超时

    Returns:
        {
            "success": bool,
            "total_latency_ms": float,
            "session_id": str,
            "outfit": {...},          # 段一：穿搭解析 dict
            "suggestion": {...},      # 段二：建议 dict
            "effect_image": {...},    # 段三：效果图 dict
            "error": str | None,
        }
    """
    import uuid
    t_start = time.time()

    if user_context is None:
        user_context = {}

    session_id = str(uuid.uuid4())
    result = {
        "session_id": session_id,
        "success": False,
        "total_latency_ms": 0.0,
        "outfit": None,
        "suggestion": None,
        "effect_image": None,
        "error": None,
    }

    # ════ 段一：穿搭解析 ════
    logger.info(f"段一：穿搭解析 — {Path(photo_path).name}")
    parser = OutfitParser()
    outfit_result = parser.parse(photo_path)

    if not outfit_result.success:
        result["error"] = f"段一失败: {outfit_result.error}"
        result["total_latency_ms"] = (time.time() - t_start) * 1000
        return result

    outfit_dict = OutfitParser.to_dict(outfit_result)
    result["outfit"] = outfit_dict

    logger.info(
        f"段一完成: {outfit_result.outfit_description[:50]}... "
        f"| {len(outfit_result.items)} 件 | {outfit_result.no_count}❌ "
        f"| {outfit_result.latency_ms:.0f}ms"
    )

    if skip_suggestion:
        result["success"] = True
        result["total_latency_ms"] = (time.time() - t_start) * 1000
        return result

    # ════ 段二：建议生成 ════
    logger.info("段二：建议生成")
    engine = SuggestionEngine()
    sugg_result = engine.generate(outfit_dict, user_context)

    if sugg_result.success and sugg_result.suggestion:
        result["suggestion"] = {
            "scene": sugg_result.scene,
            "skill_id": sugg_result.suggestion.skill_id,
            "skill_name": sugg_result.suggestion.skill_name,
            "headline": sugg_result.suggestion.headline,
            "why": sugg_result.suggestion.why,
            "how_to": sugg_result.suggestion.how_to,
            "expected_effect": sugg_result.suggestion.expected_effect,
            "difficulty": sugg_result.suggestion.difficulty,
            "estimated_time_seconds": sugg_result.suggestion.estimated_time_seconds,
            "encouragement": sugg_result.encouragement,
            "tone": sugg_result.tone,
        }
        logger.info(
            f"段二完成: {sugg_result.suggestion.headline} "
            f"| 场景={sugg_result.scene} "
            f"| {sugg_result.latency_ms:.0f}ms"
        )
        # [Fix 4] 记录匹配事件（供后续反馈使用）
        try:
            from core.feedback_collector import record_feedback
            record_feedback(
                user_id=user_context.get("user_id", "anonymous"),
                skill_id=sugg_result.suggestion.skill_id,
                feedback="",  # 待用户执行后填写
                outfit_data=outfit_dict,
                user_context=user_context,
                match_score=0,
                session_id=result["session_id"],
            )
        except Exception:
            pass  # 反馈记录失败不影响主流程
    else:
        logger.warning(f"段二失败（非阻塞）: {sugg_result.error}")
        result["suggestion"] = {
            "error": sugg_result.error,
            "fallback": True,
        }

    # ════ 段三：效果图生成 ════
    if not skip_rendering and result["suggestion"] and not result["suggestion"].get("fallback"):
        logger.info("段三：效果图生成")
        renderer = EffectRenderer()
        effect_result = renderer.render(
            outfit_data=outfit_dict,
            suggestion=result["suggestion"],
            photo_path=photo_path,
            user_context=user_context,
        )

        if effect_result.success:
            result["effect_image"] = {
                "image_urls": effect_result.image_urls,
                "prompt_used": effect_result.prompt_used,
                "model_used": effect_result.model_used,
                "latency_ms": effect_result.latency_ms,
            }
            logger.info(
                f"段三完成: {len(effect_result.image_urls)} 张效果图 "
                f"| {effect_result.latency_ms:.0f}ms"
            )
        else:
            logger.warning(f"段三失败（非阻塞）: {effect_result.error}")
            result["effect_image"] = {
                "error": effect_result.error,
                "fallback": True,
            }
    elif skip_rendering:
        logger.info("段三：已跳过（skip_rendering=True）")
    else:
        logger.info("段三：已跳过（段二未产生有效建议）")

    result["success"] = True
    result["total_latency_ms"] = (time.time() - t_start) * 1000
    return result


# ══════════════════════════════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    if len(sys.argv) < 2:
        print("用法: python -m core.pipeline <photo_path>")
        print("示例: python -m core.pipeline data/test_photos/IMG_8648.JPG")
        sys.exit(1)

    photo_path = sys.argv[1]
    if not Path(photo_path).exists():
        print(f"❌ 文件不存在: {photo_path}")
        sys.exit(1)

    print("🚀 启动穿搭分析管线")
    print(f"📸 照片: {photo_path}\n")

    user_context = {
        "body_shape": {
            "body_type": "矩形",
            "shoulder_hip_ratio": "肩胯同宽",
            "leg_body_ratio": "腿稍短",
            "skin_tone": "暖白",
        },
        "skill_history": {
            "mastered": [],
            "recent": [],
            "disliked": [],
        },
    }

    result = run_pipeline(photo_path, user_context)

    if not result["success"]:
        print(f"❌ 管线失败: {result['error']}")
        sys.exit(1)

    # ── 段一输出 ──
    outfit = result["outfit"]
    print("═" * 50)
    print("👔 段一：穿搭解析")
    print("═" * 50)
    print(f"  描述: {outfit['outfit_description']}")
    print(f"  风格: {outfit['overall_style']}")
    print(f"  照片质量: {outfit['photo_quality']}")
    if outfit.get("photo_quality_note"):
        print(f"  备注: {outfit['photo_quality_note']}")
    print(f"\n  识别单品 ({len(outfit['items'])} 件):")
    for item in outfit["items"]:
        extras = []
        if item.get("wearing_style") and item["wearing_style"] != "常规":
            extras.append(item["wearing_style"])
        if item.get("notes"):
            extras.append(item["notes"])
        extra = f" | {'; '.join(extras)}" if extras else ""
        print(f"    [{item['category']}] {item['category_cn']} {item['color']} {item['fit']}{extra}")

    print(f"\n  Checklist ({outfit['no_count']} ❌):")
    for c in outfit["checklist"]:
        icon = "❌" if c["result"] == "NO" else "✅"
        print(f"    {icon} {c['question']} — {c['reason']}")

    # ── 段二输出 ──
    sugg = result.get("suggestion")
    if sugg and not sugg.get("fallback"):
        print(f"\n{'═' * 50}")
        print("💡 段二：微调建议")
        print("═" * 50)
        print(f"  场景: {sugg['scene']}")
        print(f"  建议: {sugg['headline']}")
        print(f"  技巧: {sugg['skill_name']} ({sugg['skill_id']})")
        print(f"  为什么: {sugg['why']}")
        print(f"  怎么做: {sugg['how_to']}")
        print(f"  预期效果: {sugg['expected_effect']}")
        print(f"  难度: {'⭐' * sugg['difficulty']}  |  ⏱ {sugg['estimated_time_seconds']}s")
        print(f"  💬 {sugg['encouragement']}")
    elif sugg and sugg.get("fallback"):
        print(f"\n⚠️ 段二失败（降级）: {sugg['error']}")

    # ── 段三输出 ──
    effect = result.get("effect_image")
    if effect and not effect.get("fallback"):
        print(f"\n{'═' * 50}")
        print("🖼️  段三：效果图")
        print("═" * 50)
        urls = effect.get("image_urls", [])
        for i, url in enumerate(urls):
            print(f"  效果图 {i+1}: {url}")
        print(f"  模型: {effect.get('model_used', '')}")
        print(f"  耗时: {effect.get('latency_ms', 0):.0f}ms")
    elif effect and effect.get("fallback"):
        print(f"\n⚠️ 段三失败（降级）: {effect['error']}")

    print(f"\n⏱ 总耗时: {result['total_latency_ms']:.0f}ms")

#!/usr/bin/env python3
"""
两张真实照片 × 两种用户画像 = 4 组管线结果对比
验证核心卖点：「同衣不同建议」
"""
import sys
import json
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

from core.pipeline import run_pipeline

# ══════════════════════════════════════════════════════════════════
# 测试照片
# ══════════════════════════════════════════════════════════════════

PHOTOS = [
    "data/test_photos/IMG_8648.JPG",
    "data/test_photos/IMG_2944.jpg",
]

# ══════════════════════════════════════════════════════════════════
# 用户画像 A：梨形 + Clean Fit（偏精致控制）
# ══════════════════════════════════════════════════════════════════

USER_PEAR_CLEANFIT = {
    "user_id": "test_pear_cleanfit",
    "body_shape": {
        "body_type": "梨形",
        "shoulder_hip_ratio": "胯宽于肩",
        "leg_body_ratio": "腿稍短",
        "skin_tone": "暖白",
    },
    "skill_history": {
        "mastered": [],
        "recent": [],
        "disliked": [],
    },
    "preferences": {
        "preferred_style": "clean_fit",
    },
    "weather": {
        "season": "summer",
        "temperature": 28,
    },
}

# ══════════════════════════════════════════════════════════════════
# 用户画像 B：矩形 + City Boy（偏宽松街头）
# ══════════════════════════════════════════════════════════════════

USER_RECT_CITYBOY = {
    "user_id": "test_rect_cityboy",
    "body_shape": {
        "body_type": "矩形",
        "shoulder_hip_ratio": "肩胯同宽",
        "leg_body_ratio": "均衡",
        "skin_tone": "中性",
    },
    "skill_history": {
        "mastered": [],
        "recent": [],
        "disliked": [],
    },
    "preferences": {
        "preferred_style": "city_boy",
    },
    "weather": {
        "season": "summer",
        "temperature": 28,
    },
}

# ══════════════════════════════════════════════════════════════════
# 运行
# ══════════════════════════════════════════════════════════════════

def main():
    results = {}

    for photo_rel in PHOTOS:
        photo_path = Path(__file__).parent.parent / photo_rel
        if not photo_path.exists():
            print(f"❌ 照片不存在: {photo_path}")
            continue

        photo_name = Path(photo_rel).name

        for label, user_ctx in [
            ("梨形+Clean Fit", USER_PEAR_CLEANFIT),
            ("矩形+City Boy", USER_RECT_CITYBOY),
        ]:
            key = f"{photo_name} × {label}"
            print(f"\n{'='*60}")
            print(f"🚀 {key}")
            print(f"{'='*60}")

            result = run_pipeline(
                str(photo_path),
                user_context=user_ctx,
                skip_rendering=False,  # 跑完整三段
            )

            results[key] = {
                "success": result["success"],
                "session_id": result["session_id"],
                "total_latency_ms": result["total_latency_ms"],
                "error": result.get("error"),
                "outfit_description": (
                    result["outfit"]["outfit_description"]
                    if result.get("outfit")
                    else "N/A"
                ),
                "overall_style": (
                    result["outfit"]["overall_style"]
                    if result.get("outfit")
                    else "N/A"
                ),
                "checklist_no_count": (
                    result["outfit"]["no_count"]
                    if result.get("outfit")
                    else 0
                ),
                "top_skill": (
                    f"{result['suggestion']['skill_name']} ({result['suggestion']['skill_id']})"
                    if result.get("suggestion") and not result["suggestion"].get("fallback")
                    else f"FALLBACK: {result.get('suggestion', {}).get('error', 'N/A')}"
                ),
                "top_score": None,  # match_score not available in pipeline output yet
                "why": (
                    result["suggestion"]["why"]
                    if result.get("suggestion") and not result["suggestion"].get("fallback")
                    else "N/A"
                ),
                "effect_images": (
                    len(result["effect_image"]["image_urls"])
                    if result.get("effect_image") and not result["effect_image"].get("fallback")
                    else 0
                ),
                "effect_error": (
                    result["effect_image"]["error"]
                    if result.get("effect_image") and result["effect_image"].get("fallback")
                    else None
                ),
            }

            # 快速打印
            r = results[key]
            print(f"  ✅ 成功: {r['success']}")
            print(f"  📝 穿搭: {r['outfit_description'][:60]}...")
            print(f"  🎨 风格: {r['overall_style']}")
            print(f"  ❌ Checklist NO: {r['checklist_no_count']}")
            print(f"  🏆 推荐: {r['top_skill']}")
            print(f"  💡 理由: {r['why']}")
            print(f"  🖼️ 效果图: {r['effect_images']} 张")
            if r["effect_error"]:
                print(f"  ⚠️ 效果图错误: {r['effect_error']}")
            print(f"  ⏱ 耗时: {r['total_latency_ms']:.0f}ms")

    # ═══════════════════════════════════════════════════════════════
    # 对比总结
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*60}")
    print("📊 对比总结")
    print(f"{'='*60}")

    for photo_rel in PHOTOS:
        photo_name = Path(photo_rel).name
        skills_for_photo = {}
        for label in ["梨形+Clean Fit", "矩形+City Boy"]:
            key = f"{photo_name} × {label}"
            skills_for_photo[label] = results.get(key, {}).get("top_skill", "N/A")

        skill_a = skills_for_photo.get("梨形+Clean Fit", "")
        skill_b = skills_for_photo.get("矩形+City Boy", "")
        same = skill_a == skill_b
        print(f"\n📸 {photo_name}")
        print(f"   梨形+Clean Fit → {skill_a}")
        print(f"   矩形+City Boy  → {skill_b}")
        print(f"   {'✅ 差异化' if not same else '⚠️ 相同' if 'FALLBACK' not in str(skill_a) else '❌ 降级'}")

    # 保存完整结果
    output_path = Path(__file__).parent.parent / "data" / "pipeline_compare_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n📁 完整结果已保存: {output_path}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Phase 2 辅助：升级现有 5 个技巧 JSON，添加新 schema 字段。
机械字段由脚本填充，内容字段（body_modifiers, aesthetics_dimensions, estimated_impact）需手工精编。

用法：
    python3 tools/upgrade_skills.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).parent.parent / "knowledge" / "skills"

# 每个技巧的升级数据（机械字段）
UPGRADES = {
    "french_tuck.json": {
        "stage": "basic",
        "series": "tuck_methods",
        "target_gender": ["male", "female"],
        "prerequisites": [],
        "seasons": ["spring", "summer", "autumn", "winter"],
        "visual_guide_images": [],
        "visual_guide_caption": "",
        "estimated_impact": {
            "proportion": 15,
            "neatness": 10,
            "style_completion": 5
        },
        "body_modifiers": {
            "long_torso": {"bonus": 2, "note": "长躯干用户拉高腰线效果显著"},
            "short_legs": {"bonus": 2, "note": "视觉拉长腿部"},
            "thick_waist": {"bonus": 1, "note": "半塞优于全塞，不会在腹部制造紧绷感"}
        },
        "aesthetics_dimensions": [
            {"dimension": "proportion", "principle_id": "prop_visual_waist", "relevance": 10},
            {"dimension": "proportion", "principle_id": "prop_split_rule", "relevance": 8},
            {"dimension": "silhouette", "principle_id": "sil_tight_loose_balance", "relevance": 7},
            {"dimension": "silhouette", "principle_id": "sil_five_types", "relevance": 5},
            {"dimension": "body_modification", "principle_id": "body_waist_definition", "relevance": 9},
            {"dimension": "body_modification", "principle_id": "body_accentuate", "relevance": 7},
            {"dimension": "style", "principle_id": "sty_technique_variation", "relevance": 8},
            {"dimension": "occasion", "principle_id": "occ_same_clothes_different_wear", "relevance": 6},
            {"dimension": "occasion", "principle_id": "occ_formality_spectrum", "relevance": 5}
        ],
        "style_anti_patterns": []
    },
    "cuff_roll.json": {
        "stage": "basic",
        "series": "cuff_methods",
        "target_gender": ["male", "female"],
        "prerequisites": [],
        "seasons": ["spring", "summer", "autumn"],
        "weather_sensitive": True,
        "weather_min_temp": 12,
        "weather_note": "温度低于12°C时不推荐露踝技巧",
        "visual_guide_images": [],
        "visual_guide_caption": "",
        "estimated_impact": {
            "proportion": 8,
            "neatness": 12,
            "style_completion": 5
        },
        "body_modifiers": {
            "short_legs": {"bonus": 2, "note": "露踝+卷边延长腿部视觉终点"},
            "broad_shoulders": {"bonus": 1, "note": "下身细节平衡上身量感"}
        },
        "aesthetics_dimensions": [
            {"dimension": "proportion", "principle_id": "prop_exposure_ankle", "relevance": 10},
            {"dimension": "proportion", "principle_id": "prop_split_rule", "relevance": 6},
            {"dimension": "silhouette", "principle_id": "sil_tight_loose_balance", "relevance": 5},
            {"dimension": "body_modification", "principle_id": "body_accentuate", "relevance": 7},
            {"dimension": "style", "principle_id": "sty_technique_variation", "relevance": 8}
        ],
        "style_anti_patterns": []
    },
    "sleeve_fold.json": {
        "stage": "basic",
        "series": "sleeve_methods",
        "target_gender": ["male", "female"],
        "prerequisites": [],
        "seasons": ["spring", "summer", "autumn", "winter"],
        "visual_guide_images": [],
        "visual_guide_caption": "",
        "estimated_impact": {
            "proportion": 5,
            "neatness": 12,
            "style_completion": 5
        },
        "body_modifiers": {
            "narrow_shoulders": {"bonus": 1, "note": "露腕制造上半身利落感"},
            "broad_shoulders": {"bonus": 1, "note": "袖口细节柔化肩部量感"}
        },
        "aesthetics_dimensions": [
            {"dimension": "proportion", "principle_id": "prop_exposure_wrist", "relevance": 10},
            {"dimension": "silhouette", "principle_id": "sil_tight_loose_balance", "relevance": 5},
            {"dimension": "body_modification", "principle_id": "body_accentuate", "relevance": 7},
            {"dimension": "style", "principle_id": "sty_technique_variation", "relevance": 8}
        ],
        "style_anti_patterns": []
    },
    "button_rules.json": {
        "stage": "basic",
        "series": "collar_methods",
        "target_gender": ["male", "female"],
        "prerequisites": [],
        "seasons": ["spring", "summer", "autumn", "winter"],
        "visual_guide_images": [],
        "visual_guide_caption": "",
        "estimated_impact": {
            "proportion": 5,
            "neatness": 8,
            "style_completion": 10
        },
        "body_modifiers": {
            "broad_shoulders": {"bonus": 2, "note": "V领延伸柔化肩部量感"},
            "thick_waist": {"bonus": 1, "note": "V领纵向拉长躯干线条"}
        },
        "aesthetics_dimensions": [
            {"dimension": "proportion", "principle_id": "prop_vertical_extension", "relevance": 7},
            {"dimension": "silhouette", "principle_id": "sil_v_neck_extension", "relevance": 10},
            {"dimension": "body_modification", "principle_id": "body_visual_weight_shift", "relevance": 8},
            {"dimension": "body_modification", "principle_id": "body_accentuate", "relevance": 6},
            {"dimension": "occasion", "principle_id": "occ_formality_spectrum", "relevance": 10},
            {"dimension": "occasion", "principle_id": "occ_same_clothes_different_wear", "relevance": 9},
            {"dimension": "style", "principle_id": "sty_technique_variation", "relevance": 7}
        ],
        "style_anti_patterns": []
    },
    "color_echo.json": {
        "stage": "basic",
        "series": "color_methods",
        "target_gender": ["male", "female"],
        "prerequisites": [],
        "seasons": ["spring", "summer", "autumn", "winter"],
        "visual_guide_images": [],
        "visual_guide_caption": "",
        "estimated_impact": {
            "proportion": 3,
            "neatness": 5,
            "style_completion": 15
        },
        "body_modifiers": {
            "narrow_shoulders": {"bonus": 1, "note": "上半身呼应色引导视线向上"},
            "short_legs": {"bonus": 1, "note": "鞋裤同色延伸腿长"}
        },
        "aesthetics_dimensions": [
            {"dimension": "color", "principle_id": "color_echo", "relevance": 10},
            {"dimension": "color", "principle_id": "color_60_30_10", "relevance": 8},
            {"dimension": "color", "principle_id": "color_skin_tone", "relevance": 5},
            {"dimension": "color", "principle_id": "color_max_three_hues", "relevance": 5},
            {"dimension": "proportion", "principle_id": "prop_vertical_extension", "relevance": 7},
            {"dimension": "body_modification", "principle_id": "body_accentuate", "relevance": 6},
            {"dimension": "style", "principle_id": "sty_technique_variation", "relevance": 7}
        ],
        "style_anti_patterns": []
    },
}


def main():
    print("=" * 60)
    print("技巧升级脚本 — Phase 2")
    print("=" * 60)

    for filename, upgrade_data in UPGRADES.items():
        filepath = SKILLS_DIR / filename
        if not filepath.exists():
            print(f"  ⚠️ {filename}: 文件不存在，跳过")
            continue

        # 读取
        skill = json.loads(filepath.read_text(encoding="utf-8"))

        # 合并（只添加不覆盖已有字段）
        for key, value in upgrade_data.items():
            if key not in skill:
                skill[key] = value
                print(f"  + {filename}: 添加 {key}")
            else:
                # 对于 dict/list 类型，合并而不是覆盖
                if isinstance(value, dict) and isinstance(skill[key], dict):
                    for k, v in value.items():
                        if k not in skill[key]:
                            skill[key][k] = v
                    print(f"  ~ {filename}: 合并 {key}（{len(value)} 子字段）")
                elif isinstance(value, list) and len(skill[key]) == 0:
                    skill[key] = value
                    print(f"  ~ {filename}: 填充空 {key}（{len(value)} 项）")
                else:
                    pass  # 已有内容，不覆盖

        # 写回
        output = json.dumps(skill, ensure_ascii=False, indent=2)
        filepath.write_text(output, encoding="utf-8")
        print(f"  ✅ {filename}: 升级完成 ({len(output)} 字符)")

    print(f"\n✅ 全部升级完成: {len(UPGRADES)} 个技巧")

    return 0


if __name__ == "__main__":
    sys.exit(main())

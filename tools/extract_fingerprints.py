#!/usr/bin/env python3
"""
从原项目风格指纹中批量提取数据，转为 aesthetics_knowledge.json 的 style_directions 格式。

用法：
    python3 tools/extract_fingerprints.py
    → 输出合并后的完整 aesthetics_knowledge.json（覆盖原文件）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 原项目路径
FASHION_DIR = Path(__file__).parent.parent.parent / "Fashion"
MALE_DIR = FASHION_DIR / "styles" / "male"
FEMALE_DIR = FASHION_DIR / "styles" / "female"
KNOWLEDGE_FILE = Path(__file__).parent.parent / "knowledge" / "aesthetics" / "aesthetics_knowledge.json"

# 已在 Phase 1 中手动精编的 6 个风格（不覆盖）
ALREADY_CURATED = {
    "clean_fit", "japanese_city_boy", "korean_light_mature",
    "korean_minimal", "american_workwear",
    "italian_sprezzatura",  # 从百科提取，无指纹
    "japanese_wabi_sabi",   # 从百科提取，无指纹
}


def extract_male_fingerprint(filepath: Path) -> dict | None:
    """提取男装风格指纹，转为 style_directions 条目"""
    try:
        d = json.loads(filepath.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ⚠️ 跳过 {filepath.name}: {e}")
        return None

    style_id = d.get("style_id", filepath.stem)
    if style_id in ALREADY_CURATED:
        return None  # 已有精编版本，不覆盖

    fp = d.get("fingerprint", {})

    entry = {
        "name_cn": d.get("name_zh", style_id),
        "name_en": d.get("name_en", style_id),
        "essence": d.get("description", ""),
        "source": f"原项目 styles/male/{filepath.name}",
        "silhouette": fp.get("silhouette", {}),
        "color_rules": fp.get("color_rules", {}),
        "fabric": fp.get("fabric", {}),
        "layering": fp.get("layering", {"level": "低", "min_layers": 1, "max_layers": 2}),
        "formality_range": fp.get("formality_range", {"min": 1, "max": 3}),
        "key_items": _normalize_key_items(d.get("key_items", [])),
        "signature_techniques": _infer_signature_techniques(d),
        "body_modifier_bonus": d.get("body_modifier_bonus", {}),
        "related_styles": d.get("related_styles", []),
        "conflicting_styles": d.get("conflicting_styles", []),
        "tier": d.get("tier", "explore"),
    }
    return style_id, entry


def extract_female_fingerprint(filepath: Path) -> dict | None:
    """提取女装风格指纹"""
    try:
        d = json.loads(filepath.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ⚠️ 跳过 {filepath.name}: {e}")
        return None

    # 女装指纹直接用 style_id 或从目录名推断
    style_id = d.get("style_id", "")
    if not style_id:
        # 从目录名推断，如 WF-01_french_effortless → french_effortless
        parent = filepath.parent.name
        parts = parent.split("_", 1)
        style_id = parts[1] if len(parts) > 1 else parent

    fp = d.get("fingerprint", {})

    entry = {
        "name_cn": d.get("name_zh", style_id),
        "name_en": d.get("name_en", style_id),
        "essence": d.get("description", ""),
        "source": f"原项目 styles/female/{filepath.parent.name}/fingerprint.json",
        "silhouette": fp.get("silhouette", {}),
        "color_rules": fp.get("color_rules", {}),
        "fabric": fp.get("fabric", {}),
        "layering": fp.get("layering", {"level": "低", "min_layers": 1, "max_layers": 2}),
        "formality_range": fp.get("formality_range", {"min": 1, "max": 3}),
        "key_items": _normalize_key_items(d.get("key_items", [])),
        "signature_techniques": _infer_signature_techniques(d),
        "body_modifier_bonus": d.get("body_modifier_bonus", {}),
        "related_styles": d.get("related_styles", []),
        "conflicting_styles": d.get("conflicting_styles", []),
        "tier": d.get("tier", "explore"),
        "gender": "female",
    }
    return style_id, entry


def _normalize_key_items(items: list) -> list[dict]:
    """将 key_items 统一为 {category, desc, bonus} 格式"""
    result = []
    for item in items:
        normalized = {
            "category": item.get("category_code", item.get("category", "")),
            "desc": item.get("reason", item.get("description", "")),
            "bonus": item.get("bonus", 10),
        }
        result.append(normalized)
    return result


def _infer_signature_techniques(style_data: dict) -> dict:
    """
    根据风格的 key_items、描述和约束来推断标志技巧。
    这不是完美的，但提供了基础——后续 Phase 2 可以精编。
    """
    desc = style_data.get("description", "")
    name = style_data.get("name_zh", "")
    key_items = style_data.get("key_items", [])
    fabric = style_data.get("fingerprint", {}).get("fabric", {})
    silhouette = style_data.get("fingerprint", {}).get("silhouette", {})
    layering = style_data.get("fingerprint", {}).get("layering", {})

    techniques = {}

    # ── 通用推断规则 ──

    # 1. 塞法：合身/修身 → 规整全塞或精确半塞；宽松/廓形 → 随意前塞或不塞
    preferred_fits = silhouette.get("preferred", [])
    rejected_fits = silhouette.get("rejected", [])

    if "宽松" in preferred_fits and "紧身" in rejected_fits:
        if "廓形" in preferred_fits:
            techniques["french_tuck"] = {"method": "随意塞入不追求对称——宽松廓形优先", "edge_width": "5-7cm"}
            techniques["natural_stack"] = {"method": "不卷裤脚，自然堆叠——宽松风格标志"}
        else:
            techniques["french_tuck"] = {"method": "随意前塞或半塞，保持松弛感", "edge_width": "3-5cm"}

    if "合身" in preferred_fits or "修身" in preferred_fits:
        techniques["french_tuck"] = {"method": "规整半塞或全塞，保持利落线条", "edge_width": "3-5cm"}
        techniques["full_tuck"] = {"method": "规整全塞，前摆平整——精致风格标志"}

    # 2. 裤脚
    if "宽松" in preferred_fits:
        techniques["cuff_roll"] = {"method": "宽边卷边或自然堆叠——宽松廓形标配", "width": "3-5cm"}
    else:
        techniques["cuff_roll"] = {"method": "窄边卷边，利落整齐", "width": "2-3cm"}

    # 3. 袖口
    if "工装" in name or "复古" in name or "workwear" in style_data.get("style_id", ""):
        techniques["roll_to_elbow"] = {"method": "规整卷至肘下——工装风格标志"}
    elif "正式" in name or "sprezzatura" in style_data.get("style_id", ""):
        techniques["sleeve_fold"] = {"method": "袖口单折，仅解开袖口那颗扣——优雅不经意"}
    else:
        techniques["sleeve_fold"] = {"method": "基础翻折露出手腕", "width": "2-3cm"}

    # 4. 扣子
    if "正式" in desc or "商务" in desc:
        techniques["button_rules"] = {"method": "单解开扣——刚好不紧绷也不随便"}
    elif "街头" in desc or "休闲" in desc:
        techniques["button_rules"] = {"method": "解两颗扣——放松不羁"}
    else:
        techniques["button_rules"] = {"method": "根据正式度调整——单解为日常，全扣为正式"}

    # 5. 层次/领口
    layering_level = layering.get("level", "低") if isinstance(layering, dict) else "低"
    if layering_level in ("中", "高"):
        techniques["layering_collar"] = {"method": "内层领口高出外层——三露法则"}

    # 6. 颜色呼应
    techniques["color_echo"] = {"method": "选一个已有颜色做小面积呼应——精致不费力"}

    return techniques


def main():
    print("=" * 60)
    print("风格指纹批量提取工具")
    print("=" * 60)

    # ── 1. 提取男装指纹 ──
    male_entries = {}
    print(f"\n📂 男装指纹 ({MALE_DIR})")
    male_files = sorted(MALE_DIR.glob("*.json"))
    for f in male_files:
        result = extract_male_fingerprint(f)
        if result:
            sid, entry = result
            male_entries[sid] = entry
            print(f"  ✅ {sid} → {entry['name_cn']} (tier={entry['tier']})")

    # ── 2. 提取女装指纹 ──
    female_entries = {}
    print(f"\n📂 女装指纹 ({FEMALE_DIR})")
    for d in sorted(FEMALE_DIR.glob("WF-*")):
        fp = d / "fingerprint.json"
        if fp.exists():
            size = fp.stat().st_size
            if size >= 1000:  # 只提取完整指纹（≥1KB），跳过骨架
                result = extract_female_fingerprint(fp)
                if result:
                    sid, entry = result
                    female_entries[sid] = entry
                    print(f"  ✅ {sid} → {entry['name_cn']} (tier={entry['tier']}, {size}B)")
            else:
                name = d.name
                print(f"  ⏭️  {name}: 骨架 ({size}B)，跳过")

    # ── 3. 合并到现有知识库 ──
    print(f"\n📦 合并到 {KNOWLEDGE_FILE}")
    existing = json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))

    current_styles = existing.get("style_directions", {})
    print(f"  现有风格: {len(current_styles)} 个")

    # 添加男装（不覆盖已有的精编版本）
    added_male = 0
    for sid, entry in male_entries.items():
        if sid not in current_styles:
            current_styles[sid] = entry
            added_male += 1
    print(f"  新增男装: {added_male} 个")

    # 添加女装
    added_female = 0
    for sid, entry in female_entries.items():
        if sid not in current_styles:
            current_styles[sid] = entry
            added_female += 1
    print(f"  新增女装: {added_female} 个")

    existing["style_directions"] = current_styles
    existing["last_updated"] = "2026-06-29-T1"

    # ── 4. 写回 ──
    output = json.dumps(existing, ensure_ascii=False, indent=2)
    KNOWLEDGE_FILE.write_text(output, encoding="utf-8")
    print(f"\n✅ 写入完成: {len(current_styles)} 个风格方向")
    print(f"   文件大小: {len(output)} 字符")

    # ── 5. 快速统计 ──
    tiers = {}
    genders = {"male": 0, "female": 0, "universal": 0}
    for sid, s in current_styles.items():
        t = s.get("tier", "?")
        tiers[t] = tiers.get(t, 0) + 1
        g = s.get("gender", "male" if not sid.startswith("WF-") and sid not in [
            "french_effortless", "korean_girlie", "mori_kei", "new_chinese",
            "american_casual", "minimalist", "preppy", "athleisure",
            "boho", "y2k", "city_girl", "dark_academia"
        ] else "female")
        if g == "female":
            genders["female"] += 1
        else:
            genders["male"] += 1

    print(f"\n📊 统计:")
    print(f"  Tier: {tiers}")
    print(f"  性别: 男装 {genders['male']} + 女装 {genders['female']} = {len(current_styles)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

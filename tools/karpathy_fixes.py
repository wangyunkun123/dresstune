#!/usr/bin/env python3
"""Karpathy 审查修复：清理死数据、去重、标记推测数据"""

import json, sys
from pathlib import Path

SKILLS_DIR = Path(__file__).parent.parent / "knowledge" / "skills"
KNOWLEDGE_FILE = Path(__file__).parent.parent / "knowledge" / "aesthetics" / "aesthetics_knowledge.json"

def clean_skill(filepath):
    d = json.loads(filepath.read_text("utf-8"))
    changed = False
    name = d.get("name", filepath.stem)

    # Fix #4: 删除 style_variants 中"不推荐"条目（已在 style_anti_patterns 中声明）
    variants = d.get("style_variants", {})
    anti = set(d.get("style_anti_patterns", []))
    to_remove = []
    for style_id, v in variants.items():
        if isinstance(v, dict) and "不推荐" in v.get("method", ""):
            to_remove.append(style_id)
    for sid in to_remove:
        del variants[sid]
        # 确保在 anti_patterns 中（可能脚本提取漏了）
        if sid not in anti:
            anti.add(sid)
        changed = True
        print(f"  🔧 {name}: 从 style_variants 移除 {sid}（不推荐），加入 style_anti_patterns")
    if to_remove:
        d["style_anti_patterns"] = sorted(anti)

    # Fix #6: 删除空 visual_guide_images 和空 visual_guide_caption
    if d.get("visual_guide_images") == [] and d.get("visual_guide_caption") == "":
        del d["visual_guide_images"]
        del d["visual_guide_caption"]
        changed = True

    if changed:
        filepath.write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")
    return changed

def fix_knowledge_base():
    """Fix #1: 删除 principles 中的 related_skill_ids（skills 的 aesthetics_dimensions 是唯一权威源）"""
    d = json.loads(KNOWLEDGE_FILE.read_text("utf-8"))
    removed = 0
    for dim_id, dim in d.get("dimensions", {}).items():
        for p in dim.get("principles", []):
            if "related_skill_ids" in p:
                del p["related_skill_ids"]
                removed += 1
    d["last_updated"] = "2026-06-29-clean"

    # Fix #3: 标记提取风格为 techniques_inferred
    for sid, style in d.get("style_directions", {}).items():
        src = style.get("source", "")
        if "extract_fingerprints" in src.lower() or "styles/male/" in src or "styles/female/" in src:
            # 只有通过脚本提取的才标（手动精编的6个不标）
            curated = {"clean_fit", "city_boy", "korean_light_mature", "japanese_minimal", "american_retro", "italian_classic"}
            if sid not in curated:
                style["techniques_inferred"] = True

    KNOWLEDGE_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")
    print(f"  知识库: 删除 {removed} 个 related_skill_ids")
    return removed

# ── 执行 ──
print("=" * 50)
print("Karpathy 修复")
print("=" * 50)

# Fix skills
count = 0
for f in sorted(SKILLS_DIR.glob("*.json")):
    if clean_skill(f):
        count += 1
print(f"\n✅ 修复了 {count} 个技巧文件")

# Fix knowledge base
fix_knowledge_base()

# ── 验证 ──
print("\n验证修复后的加载...")
import importlib
loader = importlib.import_module("core.aesthetics_loader")
ak = loader.AestheticsKnowledge()
ak.reload()

# 检查 get_principles_for_skill 是否仍然工作（现在反索引 skills）
# 需要更新 loader 逻辑，先检查
print(f"  维度数: {len(ak.list_dimension_ids())}")
print(f"  风格数: {len(ak.get_style_list())}")

inferred = sum(1 for s in ak.get_style_list() if ak.get_style_direction(s).get("techniques_inferred"))
print(f"  标记 techniques_inferred: {inferred} 个风格")

print("\n✅ 所有修复完成")

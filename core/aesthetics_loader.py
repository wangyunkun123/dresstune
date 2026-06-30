"""
穿搭美学知识库加载器 — 加载 aesthetics_knowledge.json 并提供查询接口。

用法：
    from core.aesthetics_loader import AestheticsKnowledge

    ak = AestheticsKnowledge()
    principle = ak.get_principle("proportion", "prop_visual_waist")
    strategies = ak.get_body_strategies("梨形")
    style = ak.get_style_direction("clean_fit")
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("aesthetics_loader")


class AestheticsKnowledge:
    """
    穿搭美学知识库。

    加载 aesthetics_knowledge.json，提供维度、原则、体型策略、
    风格方向、场合画像等结构化查询。
    """

    def __init__(self, knowledge_dir: str = None):
        """
        Args:
            knowledge_dir: 知识库目录路径，默认 ../knowledge/aesthetics
        """
        if knowledge_dir is None:
            knowledge_dir = Path(__file__).parent.parent / "knowledge" / "aesthetics"
        self.knowledge_dir = Path(knowledge_dir)
        self._data: Optional[dict] = None

    # ═══════════════════════════════════════════════════════════════
    # 加载
    # ═══════════════════════════════════════════════════════════════

    @property
    def data(self) -> dict:
        """懒加载知识库 JSON"""
        if self._data is None:
            json_path = self.knowledge_dir / "aesthetics_knowledge.json"
            if not json_path.exists():
                raise FileNotFoundError(f"知识库文件不存在: {json_path}")
            with open(json_path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
            logger.info(
                f"已加载美学知识库 v{self._data.get('version', '?')}: "
                f"{len(self._data.get('dimensions', {}))} 个维度, "
                f"{len(self._data.get('style_directions', {}))} 个风格方向, "
                f"{len(self._data.get('body_type_strategies', {}))} 个体型策略"
            )
        return self._data

    def reload(self):
        """强制重新加载"""
        self._data = None
        return self.data

    # ═══════════════════════════════════════════════════════════════
    # 维度查询
    # ═══════════════════════════════════════════════════════════════

    def get_dimension(self, dimension_id: str) -> Optional[dict]:
        """获取美学维度定义"""
        return self.data.get("dimensions", {}).get(dimension_id)

    def get_dimension_principles(self, dimension_id: str) -> list[dict]:
        """获取某美学维度的所有原则"""
        dim = self.get_dimension(dimension_id)
        if dim is None:
            return []
        return dim.get("principles", [])

    def get_principle(self, dimension_id: str, principle_id: str) -> Optional[dict]:
        """获取特定美学原则"""
        for p in self.get_dimension_principles(dimension_id):
            if p.get("id") == principle_id:
                return p
        return None

    def get_all_dimensions(self) -> dict:
        """获取全部维度"""
        return self.data.get("dimensions", {})

    def list_dimension_ids(self) -> list[str]:
        """列出所有维度 ID"""
        return list(self.data.get("dimensions", {}).keys())

    # ═══════════════════════════════════════════════════════════════
    # 体型策略查询
    # ═══════════════════════════════════════════════════════════════

    def get_body_strategies(self, body_type: str) -> Optional[dict]:
        """获取某体型的穿搭策略"""
        return self.data.get("body_type_strategies", {}).get(body_type)

    def get_body_type_list(self) -> list[str]:
        """列出所有体型类型"""
        return list(self.data.get("body_type_strategies", {}).keys())

    def get_body_modifier(self, modifier_id: str) -> Optional[dict]:
        """获取身体特征修饰符（如 long_torso, short_legs）"""
        return self.data.get("body_modifiers", {}).get(modifier_id)

    def get_all_body_modifiers(self) -> dict:
        """获取全部身体修饰符"""
        return self.data.get("body_modifiers", {})

    # ═══════════════════════════════════════════════════════════════
    # 风格方向查询
    # ═══════════════════════════════════════════════════════════════

    def get_style_direction(self, style_id: str) -> Optional[dict]:
        """获取某风格方向的完整定义"""
        return self.data.get("style_directions", {}).get(style_id)

    def get_style_technique(self, style_id: str, skill_id: str) -> Optional[dict]:
        """
        获取某风格下特定技巧的执行方式。

        Example:
            ak.get_style_technique("clean_fit", "french_tuck")
            → {"method": "精确正中对准，两侧对称垂下", "edge_width": "3-5cm"}
        """
        style = self.get_style_direction(style_id)
        if style is None:
            return None
        return style.get("signature_techniques", {}).get(skill_id)

    def get_style_list(self) -> list[str]:
        """列出所有风格方向 ID"""
        return list(self.data.get("style_directions", {}).keys())

    def get_style_related(self, style_id: str) -> list[str]:
        """获取关联风格"""
        style = self.get_style_direction(style_id)
        if style is None:
            return []
        return style.get("related_styles", [])

    def get_style_conflicting(self, style_id: str) -> list[str]:
        """获取冲突风格"""
        style = self.get_style_direction(style_id)
        if style is None:
            return []
        return style.get("conflicting_styles", [])

    # ═══════════════════════════════════════════════════════════════
    # 风格方向对比查询（匹配引擎专用）
    # ═══════════════════════════════════════════════════════════════

    def is_style_compatible(self, style_id: str, skill_id: str) -> bool:
        """
        检查技巧是否与某风格兼容。
        有 signature_technique 条目 = 直接兼容。
        style_id 在 conflicting_styles 中 = 不兼容。
        """
        style = self.get_style_direction(style_id)
        if style is None:
            return True  # 未知风格，默认兼容

        # 有专属执行方式 → 直接兼容
        if skill_id in style.get("signature_techniques", {}):
            return True

        return None  # 不确定（无专属变体但也不冲突）

    def is_style_conflicting(self, style_id: str, skill_id: str) -> bool:
        """检查技巧是否明确与某风格冲突"""
        style = self.get_style_direction(style_id)
        if style is None:
            return False
        # 技巧在风格的 signature_techniques 中说明一定不会冲突
        if skill_id in style.get("signature_techniques", {}):
            return False
        # 否则检查风格冲突列表
        return False  # 当前 schema 没有 per-skill 冲突定义，预留

    # ═══════════════════════════════════════════════════════════════
    # 面料查询
    # ═══════════════════════════════════════════════════════════════

    def get_fabric_visual(self, fabric_cn: str) -> dict:
        """获取面料视觉描述（英文，用于 Seedream prompt）"""
        visuals = self.data.get("fabric_visuals", {})
        return visuals.get(fabric_cn, visuals.get("default", {}))

    # ═══════════════════════════════════════════════════════════════
    # 场合查询
    # ═══════════════════════════════════════════════════════════════

    def get_occasion_profile(self, occasion: str) -> Optional[dict]:
        """获取场合画像"""
        return self.data.get("occasion_profiles", {}).get(occasion)

    def get_style_mixing_rules(self) -> list[dict]:
        """获取风格混搭规则"""
        return self.data.get("style_mixing_rules", [])

    # ═══════════════════════════════════════════════════════════════
    # 交叉查询（匹配引擎专用）
    # ═══════════════════════════════════════════════════════════════

    def get_principles_for_skill(self, skill_id: str, skills_data: list[dict] = None) -> list[dict]:
        """
        获取某个技巧涉及的所有美学原则。
        从 skills 的 aesthetics_dimensions 反向索引（唯一权威源）。

        Args:
            skill_id: 技巧 ID
            skills_data: 已加载的技巧列表（由 SkillMatcher 提供）。
                         如果为 None，返回空列表。
        """
        matched = []
        if not skills_data:
            return matched

        # 从 skills 中找到该技巧的 aesthetics_dimensions
        skill = None
        for s in skills_data:
            if s.get("skill_id") == skill_id:
                skill = s
                break
        if not skill:
            return matched

        for dim_ref in skill.get("aesthetics_dimensions", []):
            dim_id = dim_ref.get("dimension", "")
            principle_id = dim_ref.get("principle_id", "")
            principle = self.get_principle(dim_id, principle_id)
            if principle:
                matched.append({
                    "dimension_id": dim_id,
                    "dimension_name": self.get_dimension(dim_id).get("name_cn", "") if self.get_dimension(dim_id) else "",
                    "relevance": dim_ref.get("relevance", 5),
                    **principle,
                })
        return matched

    def get_body_modifier_bonus(self, skill_id: str, modifier_id: str) -> int:
        """
        获取某身体特征对某技巧的加分。
        Example: get_body_modifier_bonus("french_tuck", "long_torso") → 2
        """
        modifier = self.get_body_modifier(modifier_id)
        if modifier is None:
            return 0
        if skill_id in modifier.get("bonus_skill_ids", []):
            return modifier.get("bonus_value", 0)
        if skill_id in modifier.get("caution_skill_ids", []):
            return -modifier.get("bonus_value", 0)
        return 0

    def get_best_skills_for_body_type(self, body_type: str) -> list[str]:
        """获取某体型最推荐的技巧 ID 列表"""
        strategies = self.get_body_strategies(body_type)
        if strategies is None:
            return []
        return strategies.get("best_skill_ids", [])


# ══════════════════════════════════════════════════════════════════
# 快速测试
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    ak = AestheticsKnowledge()
    data = ak.data

    print("=" * 60)
    print("穿搭美学知识库 — 自检")
    print("=" * 60)

    # 版本
    print(f"\n📦 版本: {data.get('version')}")

    # 维度
    dims = ak.list_dimension_ids()
    print(f"\n📐 {len(dims)} 个美学维度: {', '.join(dims)}")
    for dim_id in dims:
        principles = ak.get_dimension_principles(dim_id)
        print(f"  {dim_id}: {len(principles)} 条原则")
        for p in principles:
            skills = p.get("related_skill_ids", [])
            print(f"    - {p['id']}: {p['statement'][:40]}... → {len(skills)} 个关联技巧")

    # 体型策略
    body_types = ak.get_body_type_list()
    print(f"\n🧍 {len(body_types)} 个体型策略: {', '.join(body_types)}")
    for bt in body_types:
        s = ak.get_body_strategies(bt)
        print(f"  {bt}: {s['description']} → 推荐 {len(s.get('best_skill_ids', []))} 个技巧")

    # 身体修饰符
    modifiers = ak.get_all_body_modifiers()
    print(f"\n🔧 {len(modifiers)} 个身体修饰符:")
    for mid, m in modifiers.items():
        print(f"  {mid}: {m.get('description', '')}")

    # 风格方向
    styles = ak.get_style_list()
    print(f"\n🎨 {len(styles)} 个风格方向:")
    for sid in styles:
        s = ak.get_style_direction(sid)
        techniques = list(s.get("signature_techniques", {}).keys())
        print(f"  {sid} ({s['name_cn']}): {s['essence'][:50]}... → {len(techniques)} 个标志技巧")
        print(f"    来源: {s.get('source', '?')}")

    # 面料
    fabrics = data.get("fabric_visuals", {})
    print(f"\n🧵 {len(fabrics) - 1} 种面料视觉描述 (+ default)")

    # 场合
    occasions = data.get("occasion_profiles", {})
    print(f"\n🏢 {len(occasions)} 个场合画像: {', '.join(occasions.keys())}")

    # 混搭规则
    mixing = ak.get_style_mixing_rules()
    print(f"\n🔄 {len(mixing)} 条风格混搭规则")

    # 交叉查询测试
    print(f"\n🔍 交叉查询测试:")
    principles = ak.get_principles_for_skill("french_tuck")
    print(f"  french_tuck 涉及 {len(principles)} 条美学原则:")
    for p in principles:
        print(f"    [{p['dimension_name']}] {p['name_cn']}: {p['statement']}")

    tech = ak.get_style_technique("clean_fit", "french_tuck")
    print(f"  Clean Fit 的 french_tuck 执行方式: {tech}")

    bonus = ak.get_body_modifier_bonus("french_tuck", "long_torso")
    print(f"  long_torso 对 french_tuck 的加分: {bonus}")

    best = ak.get_best_skills_for_body_type("梨形")
    print(f"  梨形的最佳技巧: {best}")

    print(f"\n✅ 美学知识库加载器自检完成。")

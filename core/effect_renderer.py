"""
效果图生成器 — 将穿搭建议转化为 Seedream 生图 prompt，生成"调整后"效果图。

用法：
    from core.effect_renderer import EffectRenderer

    renderer = EffectRenderer()
    result = renderer.render(
        outfit_data=outfit_dict,
        suggestion={"skill_name": "法式半塞", "how_to": "...", ...},
        photo_path="original.jpg",
    )
    if result.success:
        print(f"效果图: {result.image_urls[0]}")
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from core.ai_router import AIRouter

logger = logging.getLogger("effect_renderer")


# ══════════════════════════════════════════════════════════════════
# 数据类
# ══════════════════════════════════════════════════════════════════

@dataclass
class EffectRendererResult:
    """效果图生成结果"""
    success: bool = False
    image_urls: list[str] = field(default_factory=list)
    prompt_used: str = ""
    model_used: str = ""
    latency_ms: float = 0.0
    error: Optional[str] = None


# ══════════════════════════════════════════════════════════════════
# 效果图渲染器
# ══════════════════════════════════════════════════════════════════

class EffectRenderer:
    """
    穿搭效果图生成器。

    输入段一的穿搭数据 + 段二的建议，调用 Seedream 生成"微调后"效果图。
    原照片作为参考图，保持人物身份、肤色、身形一致。
    """

    def __init__(self, router: AIRouter = None):
        """
        Args:
            router: AIRouter 实例，默认自动创建
        """
        if router is None:
            router = AIRouter()
        self.router = router

    # ═══════════════════════════════════════════════════════════════
    # 核心方法
    # ═══════════════════════════════════════════════════════════════

    def render(
        self,
        outfit_data: dict,
        suggestion: dict,
        photo_path: str,
        user_context: dict = None,
    ) -> EffectRendererResult:
        """
        生成穿搭调整后的效果图。

        Args:
            outfit_data: 段一穿搭解析 dict（OutfitParser.to_dict 格式）
            suggestion: 段二建议 dict，至少含 skill_name, how_to
            photo_path: 原始穿搭照片路径（用作身份参考图）
            user_context: 用户上下文（可选，用于身形描述）

        Returns:
            EffectRendererResult
        """
        t_start = time.time()

        # 校验输入
        if not suggestion or not suggestion.get("skill_name"):
            return EffectRendererResult(
                success=False,
                error="suggestion 为空或缺少 skill_name，无法构建生图 prompt",
            )

        photo = Path(photo_path)
        if not photo.exists():
            return EffectRendererResult(
                success=False,
                error=f"参考照片不存在: {photo_path}",
            )

        if user_context is None:
            user_context = {}

        try:
            prompt = self._build_prompt(outfit_data, suggestion, user_context)
            logger.info(f"Seedream prompt ({len(prompt)} 字符): {prompt[:200]}...")

            result = self.router.generate_image(
                task="effect_image",
                prompt=prompt,
                reference_images=[str(photo)],
                max_images=1,
            )

            latency_ms = (time.time() - t_start) * 1000

            if not result.success:
                return EffectRendererResult(
                    success=False,
                    error=result.error or "Seedream 生图失败",
                    prompt_used=prompt,
                    model_used=result.model_used,
                    latency_ms=latency_ms,
                )

            # 提取图片 URL
            image_urls = self._extract_urls(result.data)

            return EffectRendererResult(
                success=True,
                image_urls=image_urls,
                prompt_used=prompt,
                model_used=result.model_used,
                latency_ms=latency_ms,
            )

        except Exception as e:
            logger.error(f"效果图生成异常: {e}", exc_info=True)
            return EffectRendererResult(
                success=False,
                error=str(e),
                latency_ms=(time.time() - t_start) * 1000,
            )

    # ═══════════════════════════════════════════════════════════════
    # Prompt 构建
    # ═══════════════════════════════════════════════════════════════

    def _build_prompt(
        self,
        outfit_data: dict,
        suggestion: dict,
        user_context: dict,
    ) -> str:
        """
        构建 Seedream 生图 prompt（英语，Seedream 对英语响应更好）。

        Prompt 结构：
        1. 人物身形描述（来自 user_context）
        2. 当前穿搭描述（来自 outfit_data）
        3. 具体调整动作（来自 suggestion.how_to）
        4. 风格和构图要求
        """
        parts = []

        # ── 1. 主体描述 ──
        parts.append("A full-body fashion photograph of the same person as in the reference image.")

        # 身形
        body = user_context.get("body_shape") or user_context.get("body", {})
        if body:
            body_type = body.get("body_type", "")
            height = body.get("height", "")
            body_desc_parts = []
            if body_type:
                body_desc_parts.append(f"{body_type} body type")
            if height:
                body_desc_parts.append(f"{height}cm tall")
            if body_desc_parts:
                parts.append(f"The person has a {', '.join(body_desc_parts)}.")

        # ── 2. 穿搭描述 ──
        outfit_desc = self._describe_outfit(outfit_data)
        parts.append(outfit_desc)

        # ── 3. 调整动作 ──
        change_desc = self._describe_change(suggestion)
        parts.append(change_desc)

        # ── 4. 风格约束 ──
        parts.append(
            "Same location, same lighting, same background as the reference photo. "
            "Photorealistic, high resolution, natural pose, front-facing full body shot, "
            "fashion lookbook style. Do NOT change the person's face, hair, or the clothing items themselves — "
            "only apply the styling adjustment described above."
        )

        return " ".join(parts)

    def _describe_outfit(self, outfit_data: dict) -> str:
        """从穿搭数据构建服装描述段落"""
        items = outfit_data.get("items", [])
        if not items:
            desc = outfit_data.get("outfit_description", "")
            return f"They are wearing: {desc}." if desc else "They are wearing casual clothes."

        item_descs = []
        for item in items:
            parts = []
            color = item.get("color", "")
            sec = item.get("secondary_color", "")
            color_str = f"{color} and {sec}" if sec else color

            cat_cn = item.get("category_cn", "")
            fit = item.get("fit", "")
            notes = item.get("notes", "")

            if color_str and cat_cn:
                parts.append(f"{color_str} {cat_cn}")
            elif cat_cn:
                parts.append(cat_cn)

            if fit:
                parts.append(f"({fit} fit)")

            if notes:
                parts.append(f"with {notes}")

            item_descs.append(" ".join(parts))

        wearing = "They are wearing: " + ", ".join(item_descs) + "."

        # 穿着方式（过滤"常规"及变体，只保留有信息量的描述）
        wearing_styles = []
        for item in items:
            ws = item.get("wearing_style", "")
            if ws and not ws.startswith("常规"):
                wearing_styles.append(ws)
        if wearing_styles:
            wearing += f" Currently styled with: {', '.join(wearing_styles)}."

        return wearing

    def _describe_change(self, suggestion: dict) -> str:
        """将建议转化为视觉调整描述"""
        skill_name = suggestion.get("skill_name", "")
        how_to = suggestion.get("how_to", "")

        # 按技巧类型映射视觉描述
        skill_visual_map = {
            "法式半塞": "The front hem of the top is now casually tucked into the waistband "
                        "(French Tuck), with the back hem left out naturally.",
            "french_tuck": "The front hem of the top is now casually tucked into the waistband "
                          "(French Tuck), with the back hem left out naturally.",
            "裤脚卷边": "The bottom of the pants are now cuffed/rolled up once, "
                        "exposing the ankles.",
            "cuff_roll": "The bottom of the pants are now cuffed/rolled up once, "
                         "exposing the ankles.",
            "袖口翻折": "The sleeves are now rolled up, exposing the forearms.",
            "sleeve_roll": "The sleeves are now rolled up, exposing the forearms.",
            "小面积亮色点缀": "A small bright accent color accessory has been added "
                              "to create a visual focal point.",
            "color_pop": "A small bright accent color accessory has been added "
                         "to create a visual focal point.",
        }

        if skill_name in skill_visual_map:
            return f"The key styling change: {skill_visual_map[skill_name]}"

        # 没有预设映射时，用 how_to 原文（中译英由模型自行理解）
        if how_to:
            return (
                f"The key styling change: Apply this adjustment to the outfit — {how_to}. "
                f"The clothing items remain the same, only the way they are worn changes."
            )

        return "The outfit remains the same as in the reference photo."

    # ═══════════════════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _extract_urls(data: dict) -> list[str]:
        """从 Seedream API 返回中提取图片 URL"""
        if not data:
            return []
        # 标准 Seedream 返回格式
        images = data.get("data", [])
        urls = []
        for img in images:
            url = img.get("url", "")
            if url:
                urls.append(url)
        return urls


# ══════════════════════════════════════════════════════════════════
# 快速测试
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    print("=" * 60)
    print("EffectRenderer 模块加载成功")
    print("=" * 60)

    renderer = EffectRenderer()

    # 模拟数据
    mock_outfit = {
        "outfit_description": "白色宽松短袖T恤搭配深蓝色直筒牛仔裤",
        "items": [
            {
                "category": "TS", "category_cn": "短袖T恤",
                "color": "白色", "secondary_color": "",
                "fit": "宽松", "wearing_style": "常规（下摆未塞）",
                "notes": "纯棉面料，微落肩",
            },
            {
                "category": "JEANS", "category_cn": "牛仔裤",
                "color": "深蓝色", "secondary_color": "",
                "fit": "直筒", "wearing_style": "常规穿着",
                "notes": "",
            },
        ],
    }

    mock_suggestion = {
        "skill_name": "法式半塞",
        "how_to": "捏住T恤前摆中间一小块，塞进裤腰3-4cm，后摆自然垂下",
    }

    mock_context = {
        "body_shape": {"body_type": "梨形", "height": 170},
    }

    prompt = renderer._build_prompt(mock_outfit, mock_suggestion, mock_context)
    print(f"\nPrompt ({len(prompt)} 字符):")
    print(prompt)
    print("\n✅ EffectRenderer 自检完成。调用 renderer.render() 生成真实效果图。")

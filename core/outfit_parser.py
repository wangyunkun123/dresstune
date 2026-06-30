from __future__ import annotations

"""
穿搭解析器 — 调用视觉模型解析用户穿搭照片，提取结构化穿搭数据。

用法：
  from core.outfit_parser import OutfitParser

  parser = OutfitParser()
  result = parser.parse("photo.jpg")
  if result.success:
      print(f"识别到 {len(result.items)} 件单品")
      print(f"Checklist 通过率：{7 - result.no_count}/7")

模型路由：
  - 主力：volcengine/minimax-m3（穿搭细节识别最佳）
  - 备选：volcengine/doubao-2.0-lite（快速但细节少）
  - DeepSeek V4 Vision 不支持 image_url 格式，已排除
"""

import logging
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from core.ai_router import AIRouter, extract_json

logger = logging.getLogger("outfit_parser")


# ══════════════════════════════════════════════════════════════════
# 数据类
# ══════════════════════════════════════════════════════════════════

@dataclass
class OutfitItem:
    """单件穿搭单品"""
    category: str = ""           # 品类代码 TS/SHIRT/JEANS 等
    category_cn: str = ""        # 品类中文名
    color: str = ""              # 主色
    secondary_color: str = ""    # 辅色
    fit: str = ""                # 宽松/合身/修身
    wearing_style: str = ""      # 穿着方式（如"塞入裤腰""袖口卷起两圈""敞开穿"等）
    notes: str = ""              # 备注（面料质感、图案、特殊设计等）


@dataclass
class ChecklistItem:
    """穿搭检查项"""
    id: str = ""
    question: str = ""
    result: str = "YES"   # YES / NO
    reason: str = ""


@dataclass
class OutfitResult:
    """穿搭解析完整结果"""
    success: bool = False
    outfit_description: str = ""
    items: list[OutfitItem] = field(default_factory=list)
    checklist: list[ChecklistItem] = field(default_factory=list)
    overall_style: str = ""
    photo_quality: str = "fair"
    photo_quality_note: str = ""
    raw_response: str = ""
    model_used: str = ""
    latency_ms: float = 0.0
    error: Optional[str] = None

    @property
    def no_count(self) -> int:
        """Checklist 中 NO 的数量"""
        return sum(1 for item in self.checklist if item.result == "NO")

    @property
    def no_items(self) -> list[str]:
        """所有 NO 项的 question 列表"""
        return [item.question for item in self.checklist if item.result == "NO"]


# ══════════════════════════════════════════════════════════════════
# 解析器
# ══════════════════════════════════════════════════════════════════

class OutfitParser:
    """穿搭照片解析器。

    调用 VLM 分析照片，提取结构化穿搭数据：
    - 单品列表（品类、颜色、合身度、穿着方式）
    - 7 项基本检查（上装/下装/鞋/颜色/风格/比例/场合）
    - 整体风格和照片质量评估
    """

    def __init__(self, router: AIRouter | None = None, prompt_dir: str | None = None):
        """
        Args:
            router: AIRouter 实例，默认自动创建
            prompt_dir: prompt 模板目录，默认 ../prompts
        """
        self._router = router
        self._prompt_dir = prompt_dir
        self._system_prompt: Optional[str] = None

    @property
    def router(self) -> AIRouter:
        """懒加载 AIRouter"""
        if self._router is None:
            self._router = AIRouter()
        return self._router

    @property
    def prompt_dir_path(self) -> Path:
        """prompt 模板目录路径"""
        if self._prompt_dir is None:
            return Path(__file__).parent.parent / "prompts"
        return Path(self._prompt_dir)

    @property
    def system_prompt(self) -> str:
        """懒加载 prompts/outfit_parse.md"""
        if self._system_prompt is None:
            prompt_path = self.prompt_dir_path / "outfit_parse.md"
            if not prompt_path.exists():
                raise FileNotFoundError(f"Prompt 文件不存在: {prompt_path}")
            self._system_prompt = prompt_path.read_text(encoding="utf-8")
        return self._system_prompt

    def parse(self, photo_path: str) -> OutfitResult:
        """
        解析穿搭照片，返回结构化穿搭数据。

        流程：
        1. 检查文件是否存在
        2. 调用 VLM（主力 MiniMax-M3，失败降级到豆包 Lite）
        3. 从 VLM 返回中提取 JSON
        4. 构造 OutfitResult 返回

        Args:
            photo_path: 照片文件路径

        Returns:
            OutfitResult: 解析结果。success=True 表示解析成功。
        """
        t_start = time.time()

        # 1. 检查文件存在
        photo = Path(photo_path)
        if not photo.exists():
            return OutfitResult(
                success=False,
                error=f"文件不存在: {photo_path}",
                latency_ms=(time.time() - t_start) * 1000,
            )

        # 2. 调用 VLM
        try:
            result = self.router.chat(
                task="outfit_parsing",
                system_prompt=self.system_prompt,
                user_message="请分析这张照片中的穿搭，严格按照 JSON 格式输出。",
                images=[str(photo)],
            )
        except Exception as e:
            logger.error(f"VLM 调用异常: {e}")
            return OutfitResult(
                success=False,
                error=f"VLM 调用失败: {e}",
                latency_ms=(time.time() - t_start) * 1000,
            )

        if not result.success:
            return OutfitResult(
                success=False,
                error=f"VLM 调用失败: {result.error}",
                model_used=result.model_used,
                latency_ms=result.latency_ms,
            )

        raw_response = result.data if isinstance(result.data, str) else str(result.data)

        # 3. 提取 JSON
        parsed = extract_json(raw_response)
        if parsed is None:
            logger.warning(f"JSON 解析失败，原始返回前500字符: {raw_response[:500]}")
            return OutfitResult(
                success=False,
                error="JSON 解析失败，VLM 返回格式不符合预期",
                raw_response=raw_response,
                model_used=result.model_used,
                latency_ms=result.latency_ms,
            )

        # 4. 构造 OutfitResult
        try:
            items = [
                OutfitItem(
                    category=item.get("category", ""),
                    category_cn=item.get("category_cn", ""),
                    color=item.get("color", ""),
                    secondary_color=item.get("secondary_color", ""),
                    fit=item.get("fit", ""),
                    wearing_style=item.get("wearing_style", ""),
                    notes=item.get("notes", ""),
                )
                for item in parsed.get("items", [])
            ]

            checklist = [
                ChecklistItem(
                    id=item.get("id", ""),
                    question=item.get("question", ""),
                    result=item.get("result", "YES"),
                    reason=item.get("reason", ""),
                )
                for item in parsed.get("checklist", [])
            ]

            return OutfitResult(
                success=True,
                outfit_description=parsed.get("outfit_description", ""),
                items=items,
                checklist=checklist,
                overall_style=parsed.get("overall_style", ""),
                photo_quality=parsed.get("photo_quality", "fair"),
                photo_quality_note=parsed.get("photo_quality_note", ""),
                raw_response=raw_response,
                model_used=result.model_used,
                latency_ms=result.latency_ms,
            )
        except Exception as e:
            logger.error(f"构造 OutfitResult 失败: {e}")
            return OutfitResult(
                success=False,
                error=f"解析结果构造失败: {e}",
                raw_response=raw_response,
                model_used=result.model_used,
                latency_ms=result.latency_ms,
            )

    def parse_to_dict(self, photo_path: str) -> dict:
        """同 parse() 但返回 dict，方便下游直接消费。"""
        return OutfitParser.to_dict(self.parse(photo_path))

    @staticmethod
    def to_dict(result: OutfitResult) -> dict:
        """OutfitResult → dict 纯数据转换，不调 API。"""
        return {
            "success": result.success,
            "outfit_description": result.outfit_description,
            "items": [
                {
                    "category": item.category,
                    "category_cn": item.category_cn,
                    "color": item.color,
                    "secondary_color": item.secondary_color,
                    "fit": item.fit,
                    "wearing_style": item.wearing_style,
                    "notes": item.notes,
                }
                for item in result.items
            ],
            "checklist": [
                {
                    "id": item.id,
                    "question": item.question,
                    "result": item.result,
                    "reason": item.reason,
                }
                for item in result.checklist
            ],
            "overall_style": result.overall_style,
            "photo_quality": result.photo_quality,
            "photo_quality_note": result.photo_quality_note,
            "no_count": result.no_count,
            "no_items": result.no_items,
            "model_used": result.model_used,
            "latency_ms": result.latency_ms,
            "error": result.error,
        }


# ══════════════════════════════════════════════════════════════════
# 快速测试
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("OutfitParser 模块加载测试")
    print("=" * 60)

    parser = OutfitParser()
    print(f"\nPrompt 长度: {len(parser.system_prompt)} 字符")

    # 自动找 test_photos 下第一张照片
    test_dir = Path(__file__).parent.parent / "data" / "test_photos"
    if test_dir.exists():
        photos = sorted(test_dir.glob("*"))
        photos = [p for p in photos if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
        if photos:
            first_photo = photos[0]
            print(f"\n测试照片: {first_photo.name}")
            print("正在解析（调用 VLM，预计 15-30 秒）...")

            result = parser.parse(str(first_photo))
            if result.success:
                print(f"\n✅ 解析成功")
                print(f"   描述: {result.outfit_description}")
                print(f"   风格: {result.overall_style}")
                print(f"   单品数: {len(result.items)}")
                for item in result.items:
                    print(f"     - {item.category_cn}({item.category}): {item.color}, {item.fit}, {item.wearing_style}")
                print(f"   Checklist 通过率: {7 - result.no_count}/7")
                if result.no_count > 0:
                    print(f"   NO 项: {result.no_items}")
                print(f"   照片质量: {result.photo_quality}")
                print(f"   模型: {result.model_used}")
                print(f"   耗时: {result.latency_ms:.0f}ms")
            else:
                print(f"\n❌ 解析失败: {result.error}")
        else:
            print(f"\n⚠️  {test_dir} 中没有照片文件")
            print("✅ 模块加载成功（未测试 VLM 调用）")
    else:
        print(f"\n⚠️  {test_dir} 目录不存在")
        print("✅ 模块加载成功（未测试 VLM 调用）")
